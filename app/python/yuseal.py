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

Who knows the status? Only the STM32 and the verifier. Who knows whether the hand was the
owner's? Only the verifier (it recomputes the owner check from the attested features).
Linux can't forge the tag, can't read it, and can't change the features without breaking it.

Needs only `cryptography>=48` (ML-DSA built in; no liboqs build).
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
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

NORMAL, STEP_UP, DURESS = "N", "S", "D"
SEVERITY = {NORMAL: 0, STEP_UP: 1, DURESS: 2}
STEP_UP_AT, DURESS_AT = 40, 70  # model score 0..100; must match yuseal_mcu.h


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


# ---------------------------------------------------------------- 1. the request and the core
# A request is any JSON object the customer's system wants approved. YuDuino does not interpret
# it: it only binds the approval to the exact bytes (canonical JSON) of that request.
def build_core(request: dict, *, service: str, approver: str, device: str, nonce: str) -> dict:
    """The part every proof covers. No expiry field: the device has no trusted clock,
    so the verifier times the nonce it issued."""
    return {
        "v": 3, "suite": SUITE, "type": str(request.get("action", "request")) if isinstance(request, dict) else "request",
        "rp": service,                          # which service this is for (stops relaying to another)
        "who": approver, "device": device,
        "request": b64(sha256(canonical(request))),
        "nonce": nonce,                         # one-time, issued and timed by the verifier
    }


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
    """The one decision rule. The model can raise the alarm, never lower it. Fail closed."""
    if veto:
        return DURESS
    if not isinstance(score, int) or isinstance(score, bool) or score < 0 or score > 100:
        return DURESS
    if score >= DURESS_AT:
        return DURESS
    if score >= STEP_UP_AT:
        return STEP_UP
    return NORMAL


def model_to_score(model: dict | None) -> int:
    """Turn the edge model's reply (edge_model.py) into the 0..100 integer the STM32 takes. -1 = no usable verdict."""
    try:
        s = float(model["duress_score"])
    except (TypeError, KeyError, ValueError):
        return -1
    return round(s * 100) if 0.0 <= s <= 1.0 else -1


def mcu_keys(k_mcu: bytes) -> tuple[bytes, bytes]:
    """(k_rel, k_tag). k_rel never leaves the STM32; k_tag is shared with the verifier."""
    return hmac256(k_mcu, b"YS3/release-key"), hmac256(k_mcu, b"YS3/tag-key")


def mcu_profile_key(k_mcu: bytes) -> bytes:
    """The AES-256 key that encrypts the profile (baseline and model) at rest. Derived on the STM32,
    never stored on Linux. Not tied to an approval, because the baseline is learned all day."""
    return hmac256(k_mcu, b"YS3/profile-key")


# ---------------------------------------------------------------- the STM32's per-hour baseline
BL_SENSORS = ("humidity", "moisture", "shake_rms", "temp_c")   # this order, as in baseline_mcu.h
BL_HOURS, BL_CAP, BL_MIN_N = 24, 1000, 20
BL_HOUR_BYTES = len(BL_SENSORS) * 18


class HourBaseline:
    """Python twin of yuseal::HourBaseline: per hour of day and sensor, a rolling mean and variance.
    Exact for the first BL_CAP samples, then a rolling window of about BL_CAP samples."""

    def __init__(self):
        self.s = [[[0, 0.0, 0.0] for _ in BL_SENSORS] for _ in range(BL_HOURS)]   # n, mean, var

    def add(self, hour: int, v) -> None:
        if not 0 <= hour < BL_HOURS:
            return
        for st, x in zip(self.s[hour], v):
            st[0] = min(st[0] + 1, BL_CAP)
            alpha = 1.0 / st[0]
            delta = x - st[1]
            st[1] += alpha * delta
            st[2] = (1.0 - alpha) * (st[2] + alpha * delta * delta)

    def z(self, hour: int, v) -> list[float] | None:
        """z-scores of v against this hour's baseline, or None if the hour has too little data."""
        if not 0 <= hour < BL_HOURS:
            return None
        out = []
        for st, x in zip(self.s[hour], v):
            if st[0] < BL_MIN_N:
                return None
            sd, floor = st[2] ** 0.5, 1e-3 * (1.0 + abs(st[1]))
            out.append((x - st[1]) / (sd if sd > floor else floor))
        return out

    def count(self, hour: int) -> int:
        return self.s[hour][0][0] if 0 <= hour < BL_HOURS else 0

    def export_hour(self, hour: int) -> bytes:
        import struct
        return b"".join(struct.pack("<Hdd", n, m, var) for n, m, var in self.s[hour])

    def import_hour(self, hour: int, raw: bytes) -> bool:
        import struct
        if not 0 <= hour < BL_HOURS or len(raw) != BL_HOUR_BYTES:
            return False
        new = [list(struct.unpack("<Hdd", raw[18 * i:18 * i + 18])) for i in range(len(BL_SENSORS))]
        if any(n > BL_CAP or not (var >= 0) or m != m or var == float("inf") or abs(m) == float("inf")
               for n, m, var in new):
            return False
        self.s[hour] = new
        return True


def mcu_tag(k_tag: bytes, status: str, digest: bytes, click_age: int, grip: int, features) -> bytes:
    return hmac256(k_tag, b"YS3/tag" + status.encode() + digest + click_age.to_bytes(2, "big")
                   + bytes([grip]) + features_hash(features))


class SoftMcu:
    """Python twin of yuseal::Mcu, for tests and for running without a board."""
    IDLE, ARMED = 0, 1

    def __init__(self, k_mcu: bytes):
        self._k_rel, self._k_tag = mcu_keys(k_mcu)
        self._k_prof = mcu_profile_key(k_mcu)
        self.baseline = HourBaseline()
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

    def profile_key(self) -> bytes:
        return self._k_prof

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


# ---------------------------------------------------------------- 5. the owner check (verifier side)
# The verifier compares the STM32-attested features with the registered user's own baseline
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
    """What the verifier knows about one approver (from their enrolment package)."""
    yk_pub: ec.EllipticCurvePublicKey | None   # FIDO2 mode: the credential's public key
    pq_pub: mldsa.MLDSA65PublicKey
    k_tag: bytes  # shared with that device's STM32
    yk_hmac_key: bytes | None = None  # HMAC-SHA1 fallback mode: the slot's key. Weaker: the verifier holds a secret
    baseline: Baseline = field(default_factory=Baseline)
    unknown_hands: list = field(default_factory=list)  # times of recent not-the-owner rejections
    locked: bool = False


# Every failure answers the requester the same way, so a failed attempt says nothing about why.
FAIL_PUBLIC = "unavailable"
VERDICT = {NORMAL: "normal", STEP_UP: "step_up", DURESS: "duress"}


def _member_to_dict(m: "Member") -> dict:
    return {"yk_pub_der": b64(m.yk_pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)) if m.yk_pub else "",
            "pq_pub": b64(m.pq_pub.public_bytes_raw()), "k_tag": b64(m.k_tag),
            "yk_hmac_key": b64(m.yk_hmac_key) if m.yk_hmac_key else "",
            "baseline": [[h, f] for h, f in m.baseline.samples],
            "unknown_hands": m.unknown_hands, "locked": m.locked}


def _member_from_dict(d: dict) -> "Member":
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    m = Member(load_der_public_key(unb64(d["yk_pub_der"])) if d.get("yk_pub_der") else None,
               mldsa.MLDSA65PublicKey.from_public_bytes(unb64(d["pq_pub"])), unb64(d["k_tag"]),
               unb64(d["yk_hmac_key"]) if d.get("yk_hmac_key") else None)
    m.baseline.samples = [(h, list(f)) for h, f in d.get("baseline", [])]
    m.unknown_hands, m.locked = list(d.get("unknown_hands", [])), bool(d.get("locked", False))
    return m


@dataclass
class Verifier:
    """The reference verifier: a library the customer calls from their own system. It is not a
    service. It issues one-time nonces, checks the three proofs and the owner check, and returns
    what it found; what to do with the answer is the customer's decision.

    check() returns {"ok": bool, "verdict": ..., "public": ..., "status": N/S/D, ...} where
    `verdict` is the real outcome (normal, step_up, duress, reject, unknown_hand) and `public` is
    the only thing the requester should be shown: "accepted" for both normal and duress (a decoy
    looks identical), "step_up" for an uncertain result, and one plain "unavailable" for every failure."""
    rp_id: str
    members: dict[str, Member] = field(default_factory=dict)
    open_nonces: dict[str, float] = field(default_factory=dict)
    alerts: list = field(default_factory=list)  # (who, why) events the customer can read and clear

    def enrol(self, user: str, package: dict) -> None:
        """Register a member from the enrolment package `main.py enrol` prints (public data and the
        tag key; plus the HMAC-SHA1 slot key in the fallback mode). `seed` is the supervised
        enrolment click's sensor summary: the first baseline sample."""
        if user in self.members:
            raise ValueError("already enrolled; remove the member first")
        if bool(package.get("yk_pub_der")) == bool(package.get("yk_hmac_key")):
            raise ValueError("give exactly one of yk_pub_der (FIDO2) or yk_hmac_key (HMAC-SHA1)")
        self.members[user] = _member_from_dict(package)
        for f in package.get("seed", []):
            if len(f) == N_FEATURES:
                self.members[user].baseline.add(f, time.gmtime().tm_hour)

    def to_json(self) -> str:
        return json.dumps({"rp_id": self.rp_id, "nonces": self.open_nonces, "alerts": self.alerts,
                           "members": {u: _member_to_dict(m) for u, m in self.members.items()}})

    @classmethod
    def from_json(cls, text: str) -> "Verifier":
        d = json.loads(text)
        return cls(d["rp_id"], {u: _member_from_dict(m) for u, m in d["members"].items()},
                   dict(d.get("nonces", {})), [tuple(a) for a in d.get("alerts", [])])

    def new_nonce(self, now: float | None = None) -> str:
        n = b64(os.urandom(16))
        self.open_nonces[n] = time.time() if now is None else now
        return n

    def _fail(self, reason: str) -> dict:
        return {"ok": False, "public": FAIL_PUBLIC, "verdict": "reject", "reason": reason}

    def check(self, env: dict, request: dict, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        try:
            core = env["core"]
            m = self.members[core["who"]]
            if m.locked:
                return self._fail("member locked after repeated unknown hands")
            if core["v"] != 3 or core["suite"] != SUITE or core["rp"] != self.rp_id:
                raise ValueError("wrong suite or service")
            if core["request"] != b64(sha256(canonical(request))):
                raise ValueError("request changed after approval")
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
        del self.open_nonces[core["nonce"]]
        if band == NOT_OWNER:
            # A hand that isn't the registered user's.
            m.unknown_hands = [t for t in m.unknown_hands if now - t < LOCK_WINDOW_S] + [now]
            self.alerts.append((core["who"], "unknown hand"))
            if len(m.unknown_hands) >= LOCK_AFTER:
                m.locked = True
                self.alerts.append((core["who"], "locked after repeated unknown hands"))
            return {"ok": False, "public": FAIL_PUBLIC, "verdict": "unknown_hand", "status": status,
                    "owner_score": score, "owner_band": band, "reason": "not the registered user's hand"}
        m.unknown_hands.clear()
        # The verifier may only make things stricter, never looser.
        if band == UNCERTAIN and status == NORMAL:
            status = STEP_UP
        if status == NORMAL and band in (OWNER_LIKE, LEARNING):
            m.baseline.add(features, hour)  # only passed, normal approvals teach the baseline
        # Normal and duress look the same from outside: both are "accepted".
        public = "step_up" if status == STEP_UP else "accepted"
        return {"ok": True, "public": public, "verdict": VERDICT[status], "status": status,
                "owner_score": score, "owner_band": band, "reason": "ok"}


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
    """RFC 6962-style tree head over the audit log."""
    if not leaf_hashes:
        return sha256(b"").hex()
    level = [sha256(b"\x00" + bytes.fromhex(x)) for x in leaf_hashes]
    while len(level) > 1:
        nxt = [sha256(b"\x01" + level[i] + level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0].hex()
