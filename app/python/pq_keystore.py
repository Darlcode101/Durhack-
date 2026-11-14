"""Post-quantum key store. Lives only on the UNO Q.

YubiKey hmac-secret (32 B) --HKDF-SHA-256--> KEK (256-bit, RAM only)
KEK --AES-256-GCM--> encrypts two ML-DSA-65 private keys (FIPS 204):
    "normal"  signs access tokens for a clean login
    "duress"  signs tokens under duress; looks valid, verifier raises a silent alarm

On disk: ciphertexts, nonces, salt, credential, public keys, PIN hashes. No usable secret.
Python can't guarantee memory is wiped; we drop references as soon as possible.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SIG_ALG = "ML-DSA-65"
ROLES = ("normal", "duress")
STORE_PATH = os.environ.get("KEYSTORE_PATH", os.path.join(os.path.dirname(__file__), "keystore.json"))

_b64 = lambda b: base64.b64encode(b).decode()
_unb64 = base64.b64decode


def _kek(yubikey_secret: bytes, username: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"duress-auth kek v1|" + username.encode()).derive(yubikey_secret)


def _hash_pin(pin: str, salt: bytes) -> bytes:
    # Button PINs are short (3 buttons), so this only slows guessing a little.
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1)


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return {}
    with open(STORE_PATH) as f:
        return json.load(f)


def _save(store: dict):
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STORE_PATH)


def create_user(username, credential_data, salt, yubikey_secret, pin, duress_pin, baseline):
    """Generate both ML-DSA key pairs on the UNO Q and store them encrypted."""
    import oqs

    aes = AESGCM(_kek(yubikey_secret, username))
    pin_salt = os.urandom(16)
    entry = {
        "credential": _b64(credential_data),
        "hmac_salt": _b64(salt),
        "pin_salt": _b64(pin_salt),
        "pin_hash": _b64(_hash_pin(pin, pin_salt)),
        "duress_pin_hash": _b64(_hash_pin(duress_pin, pin_salt)),
        "baseline": baseline,
        "keys": {},
    }
    for role in ROLES:
        with oqs.Signature(SIG_ALG) as s:
            pk = s.generate_keypair()
            sk = s.export_secret_key()
        nonce = os.urandom(12)
        entry["keys"][role] = {
            "public": _b64(pk),
            "nonce": _b64(nonce),
            "ciphertext": _b64(aes.encrypt(nonce, sk, f"{username}|{role}".encode())),
        }
        del sk
    store = _load()
    store[username] = entry
    _save(store)
    return {role: entry["keys"][role]["public"] for role in ROLES}  # hand these to the verifier


def get_user(username: str) -> dict | None:
    return _load().get(username)


def check_pin(entry: dict, entered: str) -> str | None:
    """Returns "normal", "duress", or None for a wrong PIN."""
    salt = _unb64(entry["pin_salt"])
    h = _hash_pin(entered, salt)
    if hmac.compare_digest(h, _unb64(entry["duress_pin_hash"])):
        return "duress"
    if hmac.compare_digest(h, _unb64(entry["pin_hash"])):
        return "normal"
    return None


def issue_token(username: str, entry: dict, yubikey_secret: bytes, role: str) -> dict:
    """Decrypt the chosen ML-DSA key with the YubiKey-derived KEK and sign an access token."""
    import oqs

    k = entry["keys"][role]
    sk = AESGCM(_kek(yubikey_secret, username)).decrypt(
        _unb64(k["nonce"]), _unb64(k["ciphertext"]), f"{username}|{role}".encode()
    )  # raises InvalidTag if this isn't the enrolled YubiKey
    claims = json.dumps({"user": username, "iat": int(time.time()), "nonce": _b64(os.urandom(16))},
                        separators=(",", ":")).encode()
    with oqs.Signature(SIG_ALG, sk) as s:
        sig = s.sign(claims)
    del sk
    return {"alg": SIG_ALG, "claims": _b64(claims), "sig": _b64(sig)}
