"""YuSeal v2: the YuDuino approval envelope. Reference implementation of docs/CRYPTO.md.

One approval = one envelope, built from three independent proofs:

    yk       The YubiKey signs SHA-256(core) when touched.        WHO approved (classical)
    mcu      The STM32 makes a 32-byte HMAC tag after a correct   THAT a person pressed the PIN for
             PIN on the real buttons, over the hash of the text   exactly the text on the LED matrix,
             it showed. The tag secretly encodes the status.      and the hidden status (hash-based)
    pq_sig   ML-DSA-65 (FIPS 204) from the Linux side over        quantum-safe signature that glues
             everything above plus the audit-log link.            it all together

The STM32 half is app/sketch/yuseal_mcu.h; `SoftMcu` below is the same logic in Python and
the tests check the two agree byte for byte.

Who knows the status (normal / step-up / duress)? Only the STM32 and the guardian.
Linux never sees the PIN and can't read the tag, so malware there can't tell an attacker
that the alarm was raised, and can't make a tag for something that wasn't on the display.

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

SUITE = "YS2"  # ML-DSA-65 + ES256 (YubiKey) + HMAC-SHA-256 (STM32) + AES-256-GCM + SHA-256
PQ_CONTEXT = b"YuDuino/approval/v2"  # FIPS 204 context string: these signatures can't be reused elsewhere
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


# ---------------------------------------------------------------- 1. what the person sees
# Every field of a request is either shown on the LED matrix or the request is refused.
# Destinations are shown by NAME from the address book, never as "last few characters":
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


def render_display(request: dict, address_book: dict[str, str]) -> str:
    """Build the display text from the raw request. The device and the guardian both run this.

    `address_book` maps address -> label and is signed by the org root. Different requests
    always give different text, so approving the text is approving the request.
    """
    action = request.get("action")
    if action not in SCHEMAS or set(request) != SCHEMAS[action]:
        raise ValueError("unknown action, or a field that can't be shown; refused")
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
        raise ValueError("request too long to display in full; refused")
    return text


def build_core(request: dict, address_book: dict, *, service: str, approver: str, device: str, nonce: str) -> tuple[dict, str]:
    """Returns (core, display_text). No expiry field: the device has no trusted clock,
    so the guardian times the nonce it issued."""
    shown = render_display(request, address_book)
    core = {
        "v": 2, "suite": SUITE, "type": request["action"],
        "rp": service,                          # which service this is for (stops relaying to another)
        "who": approver, "device": device,
        "request": b64(sha256(canonical(request))),
        "display": b64(sha256(shown.encode())),  # the STM32 recomputes this from what it shows
        "nonce": nonce,                          # one-time, issued and timed by the guardian
    }
    return core, shown


def core_digest(core: dict) -> bytes:
    return sha256(canonical(core))


# ---------------------------------------------------------------- 2. the STM32 half (model of yuseal_mcu.h)
def decide_status(duress_pin: bool, score: int, veto: bool) -> str:
    """The one decision rule. Gemini can raise the alarm, never lower it. Fail closed."""
    if duress_pin or veto:
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
    """(k_pin, k_tag). k_pin never leaves the STM32; k_tag is shared with the guardian."""
    return hmac256(k_mcu, b"YS2/pin-key"), hmac256(k_mcu, b"YS2/tag-key")


def pin_tag(k_pin: bytes, pin: str) -> bytes:
    """PINs are strings over A B C (short press) and a b c (press held 0.8 s or more)."""
    return hmac256(k_pin, b"pin|" + pin.encode())


def mcu_tag(k_tag: bytes, status: str, display_hash: bytes, digest: bytes) -> bytes:
    return hmac256(k_tag, b"YS2/tag" + status.encode() + display_hash + digest)


class SoftMcu:
    """Python twin of yuseal::Mcu, for tests and for running without a board."""
    LONG_PRESS_MS, SETTLE_MS, SESSION_MS, MAX_WRONG = 800, 1500, 90000, 5
    IDLE, PIN_ENTRY, PIN_OK, LOCKED = 0, 1, 2, 3

    def __init__(self, k_mcu: bytes, pin: str, duress_pin: str):
        if pin == duress_pin or len(pin) != len(duress_pin):
            raise ValueError("PINs must differ and be the same length")
        self._k_pin, self._k_tag = mcu_keys(k_mcu)
        self._tag_n, self._tag_d = pin_tag(self._k_pin, pin), pin_tag(self._k_pin, duress_pin)
        self._pin_len = len(pin)
        self.wrong = 0
        self._clear()

    def _clear(self):
        self._pin, self._held, self._duress, self.state, self.text = "", False, False, self.IDLE, ""

    def begin(self, text: str, digest: bytes, now_ms: int = 0) -> bool:
        if self.state == self.LOCKED or not 0 < len(text) <= MAX_TEXT or any(not 0x20 <= ord(c) <= 0x7E for c in text):
            return False
        self._clear()
        self.text, self._display_hash, self._digest = text, sha256(text.encode()), digest
        self._start, self.state = now_ms, self.PIN_ENTRY
        return True

    def button_down(self, c: str, grip_held: bool, now_ms: int):
        if self.state != self.PIN_ENTRY or not grip_held or len(self._pin) >= self._pin_len or c not in "ABC":
            return
        self._pin += c
        self._down, self._held = now_ms, True

    def button_up(self, now_ms: int):
        if not self._held:
            return
        self._held = False
        if self.state == self.PIN_ENTRY and now_ms - self._down >= self.LONG_PRESS_MS:
            self._pin = self._pin[:-1] + self._pin[-1].lower()

    def tick(self, now_ms: int):
        if self.state in (self.PIN_ENTRY, self.PIN_OK) and now_ms - self._start > self.SESSION_MS:
            return self._clear()
        if self.state == self.PIN_ENTRY and len(self._pin) == self._pin_len and now_ms - self._down >= self.SETTLE_MS:
            if self._held:
                self.button_up(now_ms)
            t = pin_tag(self._k_pin, self._pin)
            n, d = _hmac.compare_digest(t, self._tag_n), _hmac.compare_digest(t, self._tag_d)
            if n or d:
                self._duress, self.wrong, self.state, self._pin = d, 0, self.PIN_OK, ""
            else:
                self.wrong += 1
                self._clear()
                if self.wrong >= self.MAX_WRONG:
                    self.state = self.LOCKED

    def unlock_salt(self) -> bytes | None:
        return hmac256(self._k_pin, b"unlock-salt") if self.state == self.PIN_OK else None

    def seal(self, score: int, veto: bool = False) -> bytes | None:
        if self.state != self.PIN_OK:
            return None
        tag = mcu_tag(self._k_tag, decide_status(self._duress, score, veto), self._display_hash, self._digest)
        self._clear()
        return tag

    def type_pin(self, pin: str, now_ms: int = 1000, grip: bool = True) -> int:
        """Test helper: press the PIN like a person would. Returns the time afterwards."""
        for ch in pin:
            self.button_down(ch.upper(), grip, now_ms)
            now_ms += 1000 if ch.islower() else 150
            self.button_up(now_ms)
            now_ms += 250
        now_ms += self.SETTLE_MS
        self.tick(now_ms)
        return now_ms


# ---------------------------------------------------------------- 3. the YubiKey half (classical; who, and a touch)
def verify_yubikey_assertion(pub: ec.EllipticCurvePublicKey, yk: dict, rp_id: str, challenge: bytes) -> None:
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
    if not auth_data[32] & 0x01:
        raise ValueError("no user presence: YubiKey was not touched")
    pub.verify(unb64(yk["signature"]), auth_data + sha256(client_data), ec.ECDSA(hashes.SHA256()))


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
        """One touch gives both the signature over `challenge` and the hmac-secret for `salt`."""
        return self.assert_(rp_id, challenge), self.hmac_secret(salt)

    def assert_(self, rp_id: str, challenge: bytes) -> dict:
        self.sign_count += 1
        auth_data = sha256(rp_id.encode()) + bytes([0x01]) + self.sign_count.to_bytes(4, "big")
        client_data = canonical({"type": "webauthn.get", "challenge": b64(challenge),
                                 "origin": f"https://{rp_id}"})
        sig = self._sk.sign(auth_data + sha256(client_data), ec.ECDSA(hashes.SHA256()))
        return {"authenticator_data": b64(auth_data), "client_data_json": b64(client_data),
                "signature": b64(sig)}


# ---------------------------------------------------------------- 4. the Linux key store (ML-DSA key at rest)
# The ML-DSA seed is wrapped under a key that needs BOTH the YubiKey (hmac-secret, one
# touch) and the STM32 (the salt it only releases after a correct PIN on the buttons).
# There is no PIN hash on Linux and Linux never sees the PIN, so a copied file can't be
# guessed offline, and the wrong-PIN lockout can't be bypassed from Linux.
def create_keystore(yk_secret: bytes) -> tuple[dict, mldsa.MLDSA65PrivateKey]:
    seed = os.urandom(32)
    nonce = os.urandom(12)
    blob = AESGCM(hkdf(yk_secret, b"kek/v2")).encrypt(nonce, seed, b"YuDuino/keystore/v2")
    return {"v": 2, "wrap": b64(nonce + blob)}, mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


def unlock(store: dict, yk_secret: bytes) -> mldsa.MLDSA65PrivateKey | None:
    raw = unb64(store["wrap"])
    try:
        seed = AESGCM(hkdf(yk_secret, b"kek/v2")).decrypt(raw[:12], raw[12:], b"YuDuino/keystore/v2")
    except InvalidTag:
        return None
    return mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


# ---------------------------------------------------------------- 6. the envelope
def _pq_tbs(env: dict) -> bytes:
    return sha256(canonical({"core": env["core"], "yk_sig": sha256(unb64(env["yk"]["signature"])).hex(),
                             "mcu": env["mcu"], "prev": env["prev"]}))


def make_envelope(core: dict, yk_assertion: dict, tag: bytes, prev_log_hash: str,
                  pq_key: mldsa.MLDSA65PrivateKey) -> dict:
    env = {"core": core, "yk": yk_assertion, "mcu": b64(tag), "prev": prev_log_hash}
    env["pq_sig"] = b64(pq_key.sign(_pq_tbs(env), PQ_CONTEXT))  # hedged (randomised) signing
    return env


@dataclass
class Member:
    """What the guardian knows about one approver (from their membership certificate)."""
    yk_pub: ec.EllipticCurvePublicKey
    pq_pub: mldsa.MLDSA65PublicKey
    k_tag: bytes  # shared with that device's STM32


@dataclass
class Verifier:
    """The guardian's check, and the only route to "execute". It can refuse or hold. It can't
    approve on its own: it can't make the YubiKey or ML-DSA signatures."""
    rp_id: str
    address_book: dict[str, str] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)
    open_nonces: dict[str, float] = field(default_factory=dict)

    def new_nonce(self, now: float | None = None) -> str:
        n = b64(os.urandom(16))
        self.open_nonces[n] = time.time() if now is None else now
        return n

    def check(self, env: dict, request: dict, now: float | None = None) -> dict:
        """Returns {"public": what the requester sees, "internal": the real outcome, "reason"}."""
        now = time.time() if now is None else now
        try:
            core = env["core"]
            m = self.members[core["who"]]
            if core["v"] != 2 or core["suite"] != SUITE or core["rp"] != self.rp_id:
                raise ValueError("wrong suite or service")
            if core["type"] != request.get("action") or core["request"] != b64(sha256(canonical(request))):
                raise ValueError("request changed after approval")
            display_hash = sha256(render_display(request, self.address_book).encode())
            if core["display"] != b64(display_hash):
                raise ValueError("what was shown doesn't match the request")
            issued = self.open_nonces.get(core["nonce"])
            if issued is None:
                raise ValueError("unknown or reused nonce")
            if now - issued > NONCE_TTL_S:
                raise ValueError("approval expired")
            digest = core_digest(core)
            verify_yubikey_assertion(m.yk_pub, env["yk"], self.rp_id, digest)
            m.pq_pub.verify(unb64(env["pq_sig"]), _pq_tbs(env), PQ_CONTEXT)
            # Which status did the STM32 seal? Try all three, in constant time each.
            tag = unb64(env["mcu"])
            hits = [s for s in (NORMAL, STEP_UP, DURESS)
                    if _hmac.compare_digest(tag, mcu_tag(m.k_tag, s, display_hash, digest))]
            if len(hits) != 1:
                raise ValueError("no valid tag from the device's buttons and display")
        except (KeyError, TypeError, ValueError, InvalidSignature) as e:
            return {"public": "rejected", "internal": "reject", "reason": str(e) or type(e).__name__}
        del self.open_nonces[core["nonce"]]
        status = hits[0]
        # The guardian may only make things stricter, never looser.
        if core["type"] in DANGER_ACTIONS and status == NORMAL:
            status = STEP_UP
        internal = {NORMAL: "execute", STEP_UP: "need_second_approver", DURESS: "hold_and_alert"}[status]
        # Normal and duress look the same from outside: both are "accepted" and queued.
        public = "need_second_approver" if status == STEP_UP else "accepted"
        return {"public": public, "internal": internal, "status": status, "reason": "ok"}


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
