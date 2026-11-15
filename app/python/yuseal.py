"""YuSeal v3: the YuDuino approval envelope (zero-input mouse mode). Reference implementation of docs/CRYPTO.md.

The device is hidden in a mouse and works exactly like a mouse: no screen, no PIN, no gesture.
The ordinary click on "process transaction" is the trigger. One approval = one envelope, built
from three independent proofs:

    yk       The YubiKey signs SHA-256(core), no touch.            WHO (classical): possession only
    mcu      The STM32 makes a 32-byte HMAC tag, but only after a  THAT a real click with a palm on the grip
             real click on the switch tap. The tag covers the      happened just before, and the sensor
             status, the request digest, the click age and a       summary the owner check is run on
             hash of the sensor summary. It secretly encodes
             the status (normal / step-up / duress).
    pq_sig   ML-DSA-65 (FIPS 204) from the Linux side over         quantum-safe signature that glues it
             everything above plus the audit-log link.             all together

The STM32 half is app/sketch/yuseal_mcu.h; `SoftMcu` below is the same logic in Python and the
tests check the two agree byte for byte.

Who knows the status? Only the STM32 and the guardian. Who knows whether the hand was the
owner's? Only the guardian (it recomputes the owner check from the attested features).
Linux can't forge the tag, can't read it, and can't change the features without breaking it.

Needs only `cryptography>=48` (ML-DSA built in; no liboqs build).
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
import re
import time
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, mldsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SUITE = "YS3"  # ML-DSA-65 + ES256 (YubiKey) + HMAC-SHA-256 (STM32) + AES-256-GCM + SHA-256
PQ_CONTEXT = b"YuDuino/approval/v3"  # FIPS 204 context string: these signatures can't be reused elsewhere
NONCE_TTL_S = 120
MAX_TEXT = 96

NORMAL, STEP_UP, DURESS = "N", "S", "D"
SEVERITY = {NORMAL: 0, STEP_UP: 1, DURESS: 2}
STEP_UP_AT, DURESS_AT = 40, 70  # Gemini score 0..100; must match yuseal_mcu.h


# ---------------------------------------------------------------- helpers
def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj) -> bytes:
    """One byte string per object: sorted keys, no spaces. Both sides hash the same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def hmac256(key: bytes, msg: bytes) -> bytes:
    return _hmac.new(key, msg, hashlib.sha256).digest()


def hkdf(key: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=b"YuDuino/" + info).derive(key)


# ---------------------------------------------------------------- 1. what a request is allowed to say
# There is no screen in mouse mode, so the summary is for the guardian and for Gemini (who check
# the request is sane), not for the person. Every field must be a known one or the request is
# refused. Destinations are named from the address book, never matched by "last few characters":
# an attacker can cheaply make an address with a chosen ending.
SCHEMAS = {
    "transfer": {"action", "amount", "asset", "to"},
    "login": {"action", "service", "user"},
    "add_address": {"action", "label", "address"},
    "delegate": {"action", "to"},
    "deploy": {"action", "target", "build"},
    "set_policy": {"action", "policy", "value"},
    "add_signer": {"action", "user"},
}
DANGER_ACTIONS = {"add_address", "delegate", "deploy", "set_policy", "add_signer"}  # always need a second approver


def _word(v, limit=24) -> str:
    s = str(v)
    if not s or len(s) > limit or any(not (c.isalnum() or c in "._-") for c in s):
        raise ValueError(f"refusing field value {s!r}")
    return s


def _label(address_book: dict, address) -> str:
    """Name for a destination. Names must be unique, or two addresses would look the same."""
    label = address_book.get(address)
    if label is None:
        raise ValueError("destination not in the address book; add it first")
    if list(address_book.values()).count(label) != 1:
        raise ValueError("address book has a duplicate name")
    return _word(label, 12)


def render_summary(request: dict, address_book: dict[str, str]) -> str:
    """Build the one-line summary of a request. The Linux side, Gemini and the guardian all run this.

    `address_book` maps address -> label and is signed by the org root. Different requests
    always give different text.
    """
    action = request.get("action")
    if action not in SCHEMAS or set(request) != SCHEMAS[action]:
        raise ValueError("unknown action, or a field that can't be summarised; refused")
    if action == "transfer":
        amount = str(request["amount"])
        if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,6})?", amount):
            raise ValueError("refusing amount")
        text = f"PAY {amount} {_word(request['asset'], 6)} TO {_label(address_book, request['to'])}"
    elif action == "login":
        text = f"LOGIN {_word(request['service'])} AS {_word(request['user'])}"
    elif action == "add_address":
        addr = _word(request["address"], 44)
        text = f"!ADD {_word(request['label'], 12)} = " + " ".join(addr[i:i + 4] for i in range(0, len(addr), 4))
    elif action == "delegate":
        text = f"!DELEGATE WALLET CONTROL TO {_label(address_book, request['to'])}"
    elif action == "deploy":
        text = f"!DEPLOY {_word(request['target'])} BUILD {_word(request['build'], 12)}"
    elif action == "set_policy":
        text = f"!POLICY {_word(request['policy'])} = {_word(request['value'])}"
    else:  # add_signer
        text = f"!ADD SIGNER {_word(request['user'])}"
    if len(text) > MAX_TEXT or any(not 0x20 <= ord(c) <= 0x7E for c in text):
        raise ValueError("request too long to summarise in full; refused")
    return text


def build_core(request: dict, address_book: dict, *, service: str, approver: str, device: str, nonce: str) -> tuple[dict, str]:
    """Returns (core, summary). No expiry field: the device has no trusted clock,
    so the guardian times the nonce it issued."""
    shown = render_summary(request, address_book)
    core = {
        "v": 3, "suite": SUITE, "type": request["action"],
        "rp": service,                          # which service this is for (stops relaying to another)
        "who": approver, "device": device,
        "request": b64(sha256(canonical(request))),
        "nonce": nonce,                          # one-time, issued and timed by the guardian
    }
    return core, shown


def core_digest(core: dict) -> bytes:
    return sha256(canonical(core))


# ---------------------------------------------------------------- 2. the STM32 half (model of yuseal_mcu.h)
CLICK_WINDOW_MS, SESSION_MS = 1500, 30000
RATE_MAX, RATE_WINDOW_MS = 10, 600000

# The sensor summary the STM32 attests, all scaled integers (order is fixed; must match the sketch).
FEATURE_NAMES = ("grip_permille", "tremor_milli", "humidity_centi", "temp_centi", "moisture_raw",
                 "click_hold_ms", "still_permille", "move_speed_milli", "click_impulse_milli", "n_samples")
N_FEATURES = len(FEATURE_NAMES)
ATTEST_LEN = 3 + 4 * N_FEATURES


def features_bytes(features) -> bytes:
    return b"".join(int(v).to_bytes(4, "big", signed=True) for v in features)


def features_hash(features) -> bytes:
    return sha256(b"YS3/features" + features_bytes(features))


def decide_status(score: int, veto: bool) -> str:
    """The one decision rule. Gemini can raise the alarm, never lower it. Fail closed."""
    if veto:
        return DURESS
    if not isinstance(score, int) or isinstance(score, bool) or score < 0 or score > 100:
        return DURESS
    if score >= DURESS_AT:
        return DURESS
    if score >= STEP_UP_AT:
        return STEP_UP
    return NORMAL


def gemini_to_score(gemini: dict | None) -> int:
    """Turn fusion_gemini's reply into the 0..100 integer the STM32 takes. -1 = no usable verdict."""
    try:
        s = float(gemini["duress_score"])
    except (TypeError, KeyError, ValueError):
        return -1
    return round(s * 100) if 0.0 <= s <= 1.0 else -1


def mcu_keys(k_mcu: bytes) -> tuple[bytes, bytes]:
    """(k_rel, k_tag). k_rel never leaves the STM32; k_tag is shared with the guardian."""
    return hmac256(k_mcu, b"YS3/release-key"), hmac256(k_mcu, b"YS3/tag-key")


def mcu_tag(k_tag: bytes, status: str, digest: bytes, click_age: int, grip: int, features) -> bytes:
    return hmac256(k_tag, b"YS3/tag" + status.encode() + digest + click_age.to_bytes(2, "big")
                   + bytes([grip]) + features_hash(features))


class SoftMcu:
    """Python twin of yuseal::Mcu, for tests and for running without a board."""
    IDLE, ARMED = 0, 1

    def __init__(self, k_mcu: bytes):
        self._k_rel, self._k_tag = mcu_keys(k_mcu)
        self._arms: list[int] = []
        self._pressed = self._have_click = self._click_grip = False
        self._down = self._click_ms = 0
        self.last_hold_ms = 0
        self._clear()

    def _clear(self):
        self.state, self._features = self.IDLE, [0] * N_FEATURES

    def click_down(self, now_ms: int, grip_held: bool):
        if self._pressed:
            return
        self._pressed, self._down, self._click_ms = True, now_ms, now_ms
        self._click_grip, self._have_click = grip_held, True

    def click_up(self, now_ms: int):
        if self._pressed:
            self._pressed = False
            self.last_hold_ms = min(now_ms - self._down, 65535)

    def arm(self, digest: bytes, now_ms: int, features) -> bool:
        if self.state == self.ARMED or not self._have_click or not self._click_grip or len(features) != N_FEATURES:
            return False
        age = now_ms - self._click_ms
        if age > CLICK_WINDOW_MS:
            return False
        if len(self._arms) == RATE_MAX and now_ms - self._arms[0] < RATE_WINDOW_MS:
            return False
        self._arms = (self._arms + [now_ms])[-RATE_MAX:]
        self._digest, self._features, self._age = digest, [int(v) for v in features], age
        self._have_click, self._arm_ms, self.state = False, now_ms, self.ARMED
        return True

    def tick(self, now_ms: int):
        if self.state == self.ARMED and now_ms - self._arm_ms > SESSION_MS:
            self._clear()

    def unlock_salt(self) -> bytes | None:
        return hmac256(self._k_rel, b"unlock-salt") if self.state == self.ARMED else None

    def attest(self) -> bytes | None:
        if self.state != self.ARMED:
            return None
        return self._age.to_bytes(2, "big") + bytes([1]) + features_bytes(self._features)

    def seal(self, score: int, veto: bool = False) -> bytes | None:
        if self.state != self.ARMED:
            return None
        tag = mcu_tag(self._k_tag, decide_status(score, veto), self._digest, self._age, 1, self._features)
        self._clear()
        return tag


def parse_attest(raw: bytes) -> tuple[int, int, list[int]]:
    if len(raw) != ATTEST_LEN:
        raise ValueError("bad attestation")
    return (int.from_bytes(raw[:2], "big"), raw[2],
            [int.from_bytes(raw[3 + 4 * i:7 + 4 * i], "big", signed=True) for i in range(N_FEATURES)])


# ---------------------------------------------------------------- 3. the YubiKey half (classical; possession, no touch)
def verify_yubikey_assertion(pub: ec.EllipticCurvePublicKey, yk: dict, rp_id: str, challenge: bytes,
                             require_up: bool = False) -> None:
    """Check a WebAuthn/FIDO2 assertion. Raises on any problem.

    Signature is ES256 over authenticatorData || SHA-256(clientDataJSON).
    """
    auth_data = unb64(yk["authenticator_data"])
    client_data = unb64(yk["client_data_json"])
    cd = json.loads(client_data)
    if cd.get("type") != "webauthn.get" or cd.get("challenge") != b64(challenge):
        raise ValueError("YubiKey signed a different challenge")
    if auth_data[:32] != sha256(rp_id.encode()):
        raise ValueError("YubiKey assertion is for another service")
    # Mouse mode: nobody touches the YubiKey, so this proves possession only. The physical
    # factor is the click the STM32 saw. A touch is demanded only if a deployment wants it.
    if require_up and not auth_data[32] & 0x01:
        raise ValueError("no user presence: YubiKey was not touched")
    pub.verify(unb64(yk["signature"]), auth_data + sha256(client_data), ec.ECDSA(hashes.SHA256()))


def verify_yubikey_proof(m, yk: dict, rp_id: str, challenge: bytes) -> None:
    """FIDO2 mode checks an ES256 assertion with the credential's public key. The HMAC-SHA1
    fallback checks the slot's response with the shared key. A member is in exactly one mode,
    so a proof of the other kind is refused (no downgrade)."""
    if yk.get("kind") == "hmac-sha1":
        if m.yk_hmac_key is None:
            raise ValueError("member is not in HMAC-SHA1 mode")
        want = _hmac.new(m.yk_hmac_key, challenge, hashlib.sha1).digest()
        if not _hmac.compare_digest(unb64(yk["response"]), want):
            raise ValueError("YubiKey HMAC-SHA1 response is wrong")
        return
    if m.yk_pub is None:
        raise ValueError("member is not in FIDO2 mode")
    verify_yubikey_assertion(m.yk_pub, yk, rp_id, challenge)


HMAC_SECRET_LABEL = b"YuDuino/ykhmac/secret"


class SoftYubiKeyHmac:
    """Test stand-in for the HMAC-SHA1 challenge-response slot (YubiKey slot 2, no touch)."""

    def __init__(self):
        self.key = os.urandom(20)
        self.public_key = None

    def calc(self, challenge: bytes) -> bytes:
        return _hmac.new(self.key, challenge, hashlib.sha1).digest()

    def hmac_secret(self, salt: bytes) -> bytes:
        return sha256(HMAC_SECRET_LABEL + self.calc(salt))

    def register(self, user: str):
        return b"hmac-sha1", None

    def assert_(self, rp_id: str, challenge: bytes) -> dict:
        return {"kind": "hmac-sha1", "response": b64(self.calc(challenge))}

    def assert_and_secret(self, rp_id: str, challenge: bytes, salt: bytes):
        return self.assert_(rp_id, challenge), self.hmac_secret(salt)


class SoftYubiKey:
    """Test stand-in that produces the same assertion format as a real YubiKey 5.

    On hardware use yubikey_auth (python-fido2) with challenge = core_digest(core).
    """

    def __init__(self):
        self._sk = ec.generate_private_key(ec.SECP256R1())
        self._cred_random = os.urandom(32)
        self.sign_count = 0
        self.public_key = self._sk.public_key()

    def hmac_secret(self, salt: bytes) -> bytes:  # the CTAP2 hmac-secret extension
        return hmac256(self._cred_random, salt)

    def register(self, user: str) -> tuple[bytes, ec.EllipticCurvePublicKey]:
        return b"soft-credential", self.public_key

    def assert_and_secret(self, rp_id: str, challenge: bytes, salt: bytes) -> tuple[dict, bytes]:
        """No touch needed (mouse mode); one call gives both the signature over `challenge` and the hmac-secret for `salt`."""
        return self.assert_(rp_id, challenge), self.hmac_secret(salt)

    def assert_(self, rp_id: str, challenge: bytes, touched: bool = False) -> dict:
        self.sign_count += 1
        auth_data = sha256(rp_id.encode()) + bytes([0x01 if touched else 0x00]) + self.sign_count.to_bytes(4, "big")
        client_data = canonical({"type": "webauthn.get", "challenge": b64(challenge),
                                 "origin": f"https://{rp_id}"})
        sig = self._sk.sign(auth_data + sha256(client_data), ec.ECDSA(hashes.SHA256()))
        return {"authenticator_data": b64(auth_data), "client_data_json": b64(client_data),
                "signature": b64(sig)}


# ---------------------------------------------------------------- 4. the Linux key store (ML-DSA key at rest)
# The ML-DSA seed is wrapped under a key from the YubiKey's hmac-secret. The salt for that
# secret is only released by the STM32 after a real click (it is armed), so a copied file or a
# stolen YubiKey alone cannot unwrap it, and Linux alone cannot ask for the salt.
def create_keystore(yk_secret: bytes) -> tuple[dict, mldsa.MLDSA65PrivateKey]:
    seed = os.urandom(32)
    nonce = os.urandom(12)
    blob = AESGCM(hkdf(yk_secret, b"kek/v3")).encrypt(nonce, seed, b"YuDuino/keystore/v3")
    return {"v": 3, "wrap": b64(nonce + blob)}, mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


def unlock(store: dict, yk_secret: bytes) -> mldsa.MLDSA65PrivateKey | None:
    raw = unb64(store["wrap"])
    try:
        seed = AESGCM(hkdf(yk_secret, b"kek/v3")).decrypt(raw[:12], raw[12:], b"YuDuino/keystore/v3")
    except InvalidTag:
        return None
    return mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


# ---------------------------------------------------------------- 5. the owner check (guardian side)
# The guardian compares the STM32-attested features with the registered user's own baseline
# (a median and a spread per feature, kept per hour of day when there is enough data). The
# baseline is only ever fed by approvals that passed, so an impostor can't teach it their hand.
OWNER_FEATURES = tuple(range(0, 9))        # everything but n_samples
LEARNING_MIN = 20                          # fewer samples than this: advisory only, nobody is rejected
OWNER_LIKE_AT, UNCERTAIN_AT = 60, 35       # owner score 0..100
OWNER_LIKE, UNCERTAIN, NOT_OWNER, LEARNING = "owner", "uncertain", "not_owner", "learning"
LOCK_AFTER, LOCK_WINDOW_S = 3, 600         # unknown-hand rejections that lock the member


@dataclass
class Baseline:
    samples: list = field(default_factory=list)  # list of (hour, feature vector)
    max_samples: int = 2000

    def add(self, features, hour: int):
        self.samples = (self.samples + [(hour, list(features))])[-self.max_samples:]

    def _pool(self, hour: int):
        near = [f for h, f in self.samples if min((h - hour) % 24, (hour - h) % 24) <= 1]
        return near if len(near) >= LEARNING_MIN else [f for _, f in self.samples]

    def score(self, features, hour: int) -> int | None:
        """0..100, how much this hand looks like the registered user's. None while learning."""
        pool = self._pool(hour)
        if len(pool) < LEARNING_MIN:
            return None
        total = 0.0
        for i in OWNER_FEATURES:
            col = sorted(f[i] for f in pool)
            med = col[len(col) // 2]
            mad = sorted(abs(v - med) for v in col)[len(col) // 2]
            spread = max(1.4826 * mad, 0.1 * abs(med), 1.0)
            total += max(0.0, 1.0 - abs(features[i] - med) / (4 * spread))
        return round(100 * total / len(OWNER_FEATURES))


def owner_band(score: int | None) -> str:
    if score is None:
        return LEARNING
    return OWNER_LIKE if score >= OWNER_LIKE_AT else UNCERTAIN if score >= UNCERTAIN_AT else NOT_OWNER


# ---------------------------------------------------------------- 6. the envelope
def _yk_proof_bytes(yk: dict) -> bytes:
    """The part of the YubiKey proof that is unique to it: an ES256 signature or an HMAC-SHA1 response."""
    return unb64(yk["signature"] if "signature" in yk else yk["response"])


def _pq_tbs(env: dict) -> bytes:
    return sha256(canonical({"core": env["core"], "yk_sig": sha256(_yk_proof_bytes(env["yk"])).hex(),
                             "mcu": env["mcu"], "attest": env["attest"], "prev": env["prev"]}))


def make_envelope(core: dict, yk_assertion: dict, tag: bytes, attest: bytes, prev_log_hash: str,
                  pq_key: mldsa.MLDSA65PrivateKey) -> dict:
    env = {"core": core, "yk": yk_assertion, "mcu": b64(tag), "attest": b64(attest), "prev": prev_log_hash}
    env["pq_sig"] = b64(pq_key.sign(_pq_tbs(env), PQ_CONTEXT))  # hedged (randomised) signing
    return env


@dataclass
class Member:
    """What the guardian knows about one approver (from their membership certificate)."""
    yk_pub: ec.EllipticCurvePublicKey | None   # FIDO2 mode: the credential's public key
    pq_pub: mldsa.MLDSA65PublicKey
    k_tag: bytes  # shared with that device's STM32
    yk_hmac_key: bytes | None = None  # HMAC-SHA1 fallback mode: the slot's key. Weaker: the guardian holds a secret
    baseline: Baseline = field(default_factory=Baseline)
    unknown_hands: list = field(default_factory=list)  # times of recent not-the-owner rejections
    locked: bool = False


# Every failure answers the requester the same way, so a failed attempt says nothing about why.
FAIL_PUBLIC = "unavailable"


@dataclass
class Verifier:
    """The guardian's check, and the only route to "execute". It can refuse, hold or lock. It can't
    approve on its own: it can't make the YubiKey or ML-DSA signatures."""
    rp_id: str
    address_book: dict[str, str] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)
    open_nonces: dict[str, float] = field(default_factory=dict)
    alerts: list = field(default_factory=list)  # (who, why); the guardian's response engine reads these

    def new_nonce(self, now: float | None = None) -> str:
        n = b64(os.urandom(16))
        self.open_nonces[n] = time.time() if now is None else now
        return n

    def _fail(self, reason: str) -> dict:
        return {"public": FAIL_PUBLIC, "internal": "reject", "reason": reason}

    def check(self, env: dict, request: dict, now: float | None = None) -> dict:
        """Returns {"public": what the requester sees, "internal": the real outcome, "reason"}."""
        now = time.time() if now is None else now
        try:
            core = env["core"]
            m = self.members[core["who"]]
            if m.locked:
                return self._fail("member locked after repeated unknown hands")
            if core["v"] != 3 or core["suite"] != SUITE or core["rp"] != self.rp_id:
                raise ValueError("wrong suite or service")
            if core["type"] != request.get("action") or core["request"] != b64(sha256(canonical(request))):
                raise ValueError("request changed after approval")
            render_summary(request, self.address_book)  # refuse anything that can't be summarised
            issued = self.open_nonces.get(core["nonce"])
            if issued is None:
                raise ValueError("unknown or reused nonce")
            if now - issued > NONCE_TTL_S:
                raise ValueError("approval expired")
            digest = core_digest(core)
            verify_yubikey_proof(m, env["yk"], self.rp_id, digest)
            m.pq_pub.verify(unb64(env["pq_sig"]), _pq_tbs(env), PQ_CONTEXT)
            click_age, grip, features = parse_attest(unb64(env["attest"]))
            if grip != 1:
                raise ValueError("no palm on the grip at the click")
            if click_age > CLICK_WINDOW_MS:
                raise ValueError("click too old: not this approval's click")
            # Which status did the STM32 seal? Try all three, in constant time each.
            tag = unb64(env["mcu"])
            hits = [s for s in (NORMAL, STEP_UP, DURESS)
                    if _hmac.compare_digest(tag, mcu_tag(m.k_tag, s, digest, click_age, grip, features))]
            if len(hits) != 1:
                raise ValueError("no valid tag from the device's click and sensors")
        except (KeyError, TypeError, ValueError, InvalidSignature) as e:
            return self._fail(str(e) or type(e).__name__)
        status = hits[0]
        hour = time.gmtime(now).tm_hour
        score = m.baseline.score(features, hour)
        band = owner_band(score)
        if band == NOT_OWNER:
            # A hand that isn't the registered user's. The nonce stays burnt for this attempt.
            del self.open_nonces[core["nonce"]]
            m.unknown_hands = [t for t in m.unknown_hands if now - t < LOCK_WINDOW_S] + [now]
            self.alerts.append((core["who"], "unknown hand"))
            if len(m.unknown_hands) >= LOCK_AFTER:
                m.locked = True
                self.alerts.append((core["who"], "locked after repeated unknown hands"))
            return {"public": FAIL_PUBLIC, "internal": "reject_unknown_hand", "status": status,
                    "owner_score": score, "owner_band": band, "reason": "not the registered user's hand"}
        del self.open_nonces[core["nonce"]]
        m.unknown_hands.clear()
        # The guardian may only make things stricter, never looser.
        if core["type"] in DANGER_ACTIONS and status == NORMAL:
            status = STEP_UP
        if band == UNCERTAIN and status == NORMAL:
            status = STEP_UP
        if status == NORMAL and band in (OWNER_LIKE, LEARNING):
            m.baseline.add(features, hour)  # only passed, normal approvals teach the baseline
        internal = {NORMAL: "execute", STEP_UP: "need_second_approver", DURESS: "hold_and_alert"}[status]
        # Normal and duress look the same from outside: both are "accepted" and queued.
        public = "need_second_approver" if status == STEP_UP else "accepted"
        return {"public": public, "internal": internal, "status": status, "owner_score": score,
                "owner_band": band, "reason": "ok"}


# ---------------------------------------------------------------- 7. the audit log
GENESIS = "0" * 64


def log_append(log: list, envelope: dict, signer: mldsa.MLDSA65PrivateKey) -> dict:
    """Hash-chained and signed. Stores the envelope's hash, never the plain status."""
    prev = log[-1]["hash"] if log else GENESIS
    body = {"seq": len(log), "t": int(time.time()), "prev": prev,
            "who": envelope["core"]["who"], "type": envelope["core"]["type"],
            "envelope": sha256(canonical(envelope)).hex()}
    h = sha256(canonical(body)).hex()
    entry = {**body, "hash": h, "sig": b64(signer.sign(bytes.fromhex(h), b"YuDuino/log/v1"))}
    log.append(entry)
    return entry


def log_verify(log: list, pub: mldsa.MLDSA65PublicKey) -> bool:
    prev = GENESIS
    for i, e in enumerate(log):
        body = {k: e[k] for k in ("seq", "t", "prev", "who", "type", "envelope")}
        h = sha256(canonical(body)).hex()
        if e["seq"] != i or e["prev"] != prev or e["hash"] != h:
            return False
        try:
            pub.verify(unb64(e["sig"]), bytes.fromhex(h), b"YuDuino/log/v1")
        except InvalidSignature:
            return False
        prev = h
    return True


def merkle_root(leaf_hashes: list[str]) -> str:
    """RFC 6962-style tree head the guardian publishes and signs (transparency log)."""
    if not leaf_hashes:
        return sha256(b"").hex()
    level = [sha256(b"\x00" + bytes.fromhex(x)) for x in leaf_hashes]
    while len(level) > 1:
        nxt = [sha256(b"\x01" + level[i] + level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0].hex()
