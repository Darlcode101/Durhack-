"""YuSeal: the YuDuino approval envelope. Reference implementation of docs/CRYPTO.md.

One approval = one envelope:

    core      what the person saw and approved (request hash, display hash, service,
              approver, device, nonce, expiry). The YubiKey signs this (FIDO2
              assertion with challenge = SHA-256(core)), so the touch is bound to it.
    sealed    a fixed-size AES-256-GCM box holding the hidden status
              (normal / step-up / duress) plus the features Gemini saw. Only the
              guardian can open it. Normal and duress boxes look identical.
    pq_sig    ML-DSA-65 (FIPS 204) over core + YubiKey signature + sealed box +
              counter + previous audit hash. Quantum-safe, and it glues everything together.

There is ONE device signing key, never a "real" key and a "decoy" key: the attacker
can't tell a decoy by checking which public key verifies it.

The sealing key ratchets forward after every approval (old keys are erased), so
someone who seizes the device later can't open old boxes and prove the user
raised the alarm.

Needs only `cryptography>=48` (ML-DSA built in; no liboqs build). Runs on the UNO Q's
Linux side for the hackathon; the STM32 port is described in docs/CRYPTO.md.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, mldsa, mlkem, x25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SUITE = "YS1"  # ML-DSA-65 + ES256 (YubiKey) + AES-256-GCM + HKDF-SHA-256 + SHA-256
PQ_CONTEXT = b"YuDuino/approval/v1"  # FIPS 204 context string: these signatures can't be reused elsewhere
SEALED_PLAINTEXT_LEN = 512  # every box is padded to this, whatever it holds
MAX_RATCHET_SKIP = 64

NORMAL, STEP_UP, DURESS = "normal", "step_up", "duress"
STEP_UP_AT, DURESS_AT = 0.4, 0.7


# ---------------------------------------------------------------- helpers
def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj) -> bytes:
    """One byte string per object: sorted keys, no spaces. Both sides hash the same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def hkdf(key: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=b"YuDuino/" + info).derive(key)


def check_code(digest: bytes) -> str:
    """4-character code shown on BOTH the LED matrix and the big screen. They must match."""
    return base64.b32encode(digest).decode()[:4]


# ---------------------------------------------------------------- 1. what the person sees
DANGER_ACTIONS = {"delegate", "deploy", "set_policy", "add_signer", "unlimited_approval"}


def render_display(request: dict) -> str:
    """The device builds the display text from the raw request itself (never the laptop's summary).

    Refuses anything it can't show in full, instead of cutting it short.
    """
    action = request["action"]
    if action == "transfer":
        text = f"PAY {request['amount']} {request['asset']} TO ..{request['to'][-6:]}"
    elif action == "login":
        text = f"LOGIN {request['service']} AS {request['user']}"
    elif action in DANGER_ACTIONS:
        text = f"!{action.upper()} {request.get('target', '')[-6:]}"
    else:
        raise ValueError(f"refusing unknown action {action!r}")
    if len(text) > 48:
        raise ValueError("request too long to display in full; refused")
    return text


def build_core(request: dict, *, service: str, approver: str, device: str, nonce: str,
               ttl_s: int = 120, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    shown = render_display(request)
    return {
        "v": 1, "suite": SUITE, "type": request["action"],
        "rp": service,                          # which service this is for (stops relaying to another)
        "who": approver, "device": device,
        "request": b64(sha256(canonical(request))),
        "display": b64(sha256(shown.encode())),  # hash of exactly what was shown
        "nonce": nonce,                          # one-time, chosen by the verifier
        "exp": int(now + ttl_s),
    }


def core_digest(core: dict) -> bytes:
    return sha256(canonical(core))


# ---------------------------------------------------------------- 2. the hidden status (duress decision)
def decide_status(*, pin_mode: str, gemini: dict | None, onboard_veto: bool) -> str:
    """Mirrors the STM32 rule. Gemini can only raise the alarm, never clear one.

    Fail closed: no verdict, or a malformed one, means DURESS.
    """
    if pin_mode == DURESS or onboard_veto:
        return DURESS
    try:
        score = float(gemini["score"])
        flagged = bool(gemini["duress"])
    except (TypeError, KeyError, ValueError):
        return DURESS
    if flagged or score >= DURESS_AT or not 0.0 <= score <= 1.0:
        return DURESS
    if score >= STEP_UP_AT:
        return STEP_UP
    return NORMAL


@dataclass
class SealChain:
    """Forward-secret sealing keys shared by one device and the guardian.

    K_0 comes from enrolment (ML-KEM-768 to the guardian). After each message:
    message key = HKDF(K_i, "msg"), K_{i+1} = HKDF(K_i, "chain"), K_i is erased.
    """
    key: bytes
    counter: int = 0

    def _step(self) -> bytes:
        msg_key = hkdf(self.key, b"seal/msg")
        self.key = hkdf(self.key, b"seal/chain")
        self.counter += 1
        return msg_key

    def seal(self, status: str, details: dict, aad: bytes) -> dict:
        payload = canonical({"status": status, **details})
        if len(payload) > SEALED_PLAINTEXT_LEN - 2:
            raise ValueError("sealed details too large")
        padded = len(payload).to_bytes(2, "big") + payload + os.urandom(SEALED_PLAINTEXT_LEN - 2 - len(payload))
        ctr = self.counter + 1
        msg_key = self._step()
        nonce = os.urandom(12)
        ct = AESGCM(msg_key).encrypt(nonce, padded, aad + ctr.to_bytes(8, "big"))
        return {"ctr": ctr, "box": b64(nonce + ct)}

    def open(self, sealed: dict, aad: bytes) -> dict:
        ctr = sealed["ctr"]
        if ctr <= self.counter or ctr - self.counter > MAX_RATCHET_SKIP:
            raise ValueError("sealed counter replayed or too far ahead")
        trial = SealChain(self.key, self.counter)
        while trial.counter < ctr - 1:  # skip messages that never arrived
            trial._step()
        msg_key = trial._step()
        raw = unb64(sealed["box"])
        padded = AESGCM(msg_key).decrypt(raw[:12], raw[12:], aad + ctr.to_bytes(8, "big"))
        self.key, self.counter = trial.key, trial.counter  # only commit after it opened
        n = int.from_bytes(padded[:2], "big")
        return json.loads(padded[2:2 + n])


def seal_root_device_side(guardian_kem_pub: mlkem.MLKEM768PublicKey,
                          guardian_x_pub: x25519.X25519PublicKey) -> tuple[bytes, dict]:
    """Enrolment: agree K_0 with the guardian using hybrid ML-KEM-768 + X25519.

    Safe if EITHER algorithm holds (ML-KEM against quantum, X25519 as the well-tested classic).
    Returns (K_0, message for the guardian)."""
    kem_ss, kem_ct = guardian_kem_pub.encapsulate()
    eph = x25519.X25519PrivateKey.generate()
    x_ss = eph.exchange(guardian_x_pub)
    eph_pub = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    k0 = hkdf(kem_ss + x_ss + sha256(kem_ct + eph_pub), b"seal/root")
    return k0, {"kem_ct": b64(kem_ct), "x_pub": b64(eph_pub)}


def seal_root_guardian_side(msg: dict, kem_key: mlkem.MLKEM768PrivateKey,
                            x_key: x25519.X25519PrivateKey) -> bytes:
    kem_ct, eph_pub = unb64(msg["kem_ct"]), unb64(msg["x_pub"])
    kem_ss = kem_key.decapsulate(kem_ct)
    x_ss = x_key.exchange(x25519.X25519PublicKey.from_public_bytes(eph_pub))
    return hkdf(kem_ss + x_ss + sha256(kem_ct + eph_pub), b"seal/root")


# ---------------------------------------------------------------- 3. the YubiKey half (classical, presence)
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
        return hmac.new(self._cred_random, salt, hashlib.sha256).digest()

    def assert_(self, rp_id: str, challenge: bytes) -> dict:
        self.sign_count += 1
        auth_data = sha256(rp_id.encode()) + bytes([0x01]) + self.sign_count.to_bytes(4, "big")
        client_data = canonical({"type": "webauthn.get", "challenge": b64(challenge),
                                 "origin": f"https://{rp_id}"})
        sig = self._sk.sign(auth_data + sha256(client_data), ec.ECDSA(hashes.SHA256()))
        return {"authenticator_data": b64(auth_data), "client_data_json": b64(client_data),
                "signature": b64(sig)}


# ---------------------------------------------------------------- 4. the device key store (PIN folded into the YubiKey)
def pin_salt(pin: str, store_salt: bytes) -> bytes:
    return sha256(b"YuDuino/pin|" + store_salt + b"|" + pin.encode())


def _kek(yk_secret: bytes, device_secret: bytes) -> bytes:
    # Two locks: the YubiKey's hmac-secret AND a secret that never leaves the device
    # (on the STM32: wrapped by the chip's hardware unique key; hackathon: a 0600 file).
    return hkdf(yk_secret + device_secret, b"kek")


def create_keystore(yubikey, device_secret: bytes, pin: str, duress_pin: str) -> tuple[dict, mldsa.MLDSA65PrivateKey]:
    """Enrolment. The ML-DSA seed is wrapped twice: once under the normal PIN, once under
    the duress PIN. No PIN hash is stored anywhere; which wrap opens tells us the mode.
    Both PINs come from one YubiKey touch (hmac-secret takes two salts)."""
    if pin == duress_pin:
        raise ValueError("PINs must differ")
    store_salt = os.urandom(16)
    seed = os.urandom(32)  # STM32: from its true RNG
    store = {"salt": b64(store_salt), "wraps": []}
    for p in sorted([pin, duress_pin], key=lambda _: os.urandom(1)):  # random order on disk
        mode = DURESS if p == duress_pin else NORMAL
        kek = _kek(yubikey.hmac_secret(pin_salt(p, store_salt)), device_secret)
        nonce = os.urandom(12)
        blob = AESGCM(kek).encrypt(nonce, seed + mode.encode().ljust(8, b"\0"), b"YuDuino/keystore/v1")
        store["wraps"].append(b64(nonce + blob))
    return store, mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


def unlock(store: dict, yk_secret_for_entered_pin: bytes, device_secret: bytes):
    """Returns (mode, signing_key), or (None, None) for a wrong PIN. Always tries every wrap."""
    kek = _kek(yk_secret_for_entered_pin, device_secret)
    found = None
    for w in store["wraps"]:
        raw = unb64(w)
        try:
            pt = AESGCM(kek).decrypt(raw[:12], raw[12:], b"YuDuino/keystore/v1")
            found = pt
        except InvalidTag:
            pass
    if found is None:
        return None, None
    return found[32:].rstrip(b"\0").decode(), mldsa.MLDSA65PrivateKey.from_seed_bytes(found[:32])


# ---------------------------------------------------------------- 5. the envelope
def _pq_tbs(env: dict) -> bytes:
    return sha256(canonical({"core": env["core"], "yk_sig": sha256(unb64(env["yk"]["signature"])).hex(),
                             "sealed": env["sealed"], "prev": env["prev"]}))


def make_envelope(core: dict, yk_assertion: dict, sealed: dict, prev_log_hash: str,
                  pq_key: mldsa.MLDSA65PrivateKey) -> dict:
    env = {"core": core, "yk": yk_assertion, "sealed": sealed, "prev": prev_log_hash}
    env["pq_sig"] = b64(pq_key.sign(_pq_tbs(env), PQ_CONTEXT))  # hedged (randomised) signing
    return env


@dataclass
class Member:
    """What the verifier knows about one approver (from their membership certificate)."""
    yk_pub: ec.EllipticCurvePublicKey
    pq_pub: mldsa.MLDSA65PublicKey
    seal: SealChain


@dataclass
class Verifier:
    """The guardian's check. The only route to "execute". It can refuse or hold; it can't approve,
    because it can't make the person's two signatures."""
    rp_id: str
    members: dict[str, Member] = field(default_factory=dict)
    open_nonces: set[str] = field(default_factory=set)

    def new_nonce(self) -> str:
        n = b64(os.urandom(16))
        self.open_nonces.add(n)
        return n

    def check(self, env: dict, request: dict, now: float | None = None) -> dict:
        """Returns {"public": what the requester sees, "internal": the real outcome, "reason"}."""
        now = time.time() if now is None else now
        try:
            core = env["core"]
            m = self.members[core["who"]]
            if core["suite"] != SUITE or core["rp"] != self.rp_id:
                raise ValueError("wrong suite or service")
            if core["request"] != b64(sha256(canonical(request))):
                raise ValueError("request changed after approval")
            if core["display"] != b64(sha256(render_display(request).encode())):
                raise ValueError("what was shown doesn't match the request")
            if core["nonce"] not in self.open_nonces:
                raise ValueError("unknown or reused nonce")
            if now > core["exp"]:
                raise ValueError("approval expired")
            digest = core_digest(core)
            verify_yubikey_assertion(m.yk_pub, env["yk"], self.rp_id, digest)
            m.pq_pub.verify(unb64(env["pq_sig"]), _pq_tbs(env), PQ_CONTEXT)
            inner = m.seal.open(env["sealed"], digest)  # also enforces the counter (no replays)
        except (KeyError, ValueError, InvalidSignature, InvalidTag) as e:
            return {"public": "rejected", "internal": "reject", "reason": str(e) or type(e).__name__}
        self.open_nonces.discard(core["nonce"])
        status = inner["status"]
        internal = {NORMAL: "execute", STEP_UP: "need_second_approver", DURESS: "hold_and_alert"}[status]
        # Normal and duress look the same from outside: both are "accepted" and queued.
        public = "need_second_approver" if status == STEP_UP else "accepted"
        return {"public": public, "internal": internal, "reason": inner}


# ---------------------------------------------------------------- 6. the audit log
GENESIS = "0" * 64


def log_append(log: list, envelope: dict, signer: mldsa.MLDSA65PrivateKey) -> dict:
    """Hash-chained, device-signed. Stores the sealed box, never the plain status."""
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
