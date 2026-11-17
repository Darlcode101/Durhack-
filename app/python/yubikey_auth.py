"""YubiKey over USB, driven directly from the UNO Q (python-fido2, CTAP2).

The YubiKey only creates key material:
  - a FIDO2 credential (its private key never leaves the YubiKey)
  - a 32-byte hmac-secret output for a given salt, returned only when touched

The UNO Q verifies the assertion itself and turns the hmac-secret into a KEK
(see pq_keystore.py). No browser, no laptop.

UNVERIFIED on hardware. Needs read/write access to /dev/hidraw* on the board
(udev rule or run as root); App Lab's container may block USB — if so run this
as a normal Python process on the board's Debian.
"""
import hashlib
import json
import os
import subprocess

from fido2.client import DefaultClientDataCollector, Fido2Client, UserInteraction
from fido2.ctap2 import Ctap2
from fido2.ctap2.extensions import HmacSecretExtension
from fido2.ctap2.pin import ClientPin
from fido2.hid import CtapHidDevice
from fido2.server import Fido2Server
from fido2.webauthn import AttestedCredentialData

RP_ID = os.environ.get("FIDO_RP_ID", "yuduino.local")
UV = "discouraged"  # no YubiKey PIN. Mouse mode has no knowledge factor at all (see docs/CRYPTO.md weak spots)

_server = Fido2Server({"id": RP_ID, "name": "Duress-aware login"}, attestation="none")


class _Prompt(UserInteraction):
    def prompt_up(self):
        print("[yubikey] key asked for a touch")  # mouse mode wants NO touch: see RealYubiKey

    def request_pin(self, permissions, rp_id):
        return os.environ.get("YUBIKEY_FIDO_PIN")  # only used if the key insists on a PIN


def _client() -> Fido2Client:
    for dev in CtapHidDevice.list_devices():
        client = Fido2Client(
            dev,
            client_data_collector=DefaultClientDataCollector(f"https://{RP_ID}"),
            user_interaction=_Prompt(),
            extensions=[HmacSecretExtension(allow_hmac_secret=True)],
        )
        if "hmac-secret" in client.info.extensions:
            return client
    raise RuntimeError("No YubiKey with hmac-secret found on USB")


def enrol(username: str) -> tuple[bytes, bytes, bytes]:
    """Create a credential on the YubiKey, then get the first hmac-secret.

    Returns (credential_data, salt, secret32). The caller stores credential_data
    and salt; the secret is used once to derive the KEK and then discarded.
    """
    client = _client()
    options, state = _server.register_begin(
        {"id": username.encode(), "name": username},
        resident_key_requirement="discouraged",
        user_verification=UV,
        authenticator_attachment="cross-platform",
    )
    result = client.make_credential({**options["publicKey"], "extensions": {"hmacCreateSecret": True}})
    cred = _server.register_complete(state, result).credential_data

    salt = os.urandom(32)
    secret = login(bytes(cred), salt, client)
    return bytes(cred), salt, secret


def login(credential_data: bytes, salt: bytes, client: Fido2Client | None = None) -> bytes:
    """Touch → verify the assertion on the UNO Q → return the 32-byte hmac-secret.

    Raises if the YubiKey isn't the enrolled one or the signature doesn't verify.
    """
    client = client or _client()
    creds = [AttestedCredentialData(credential_data)]
    options, state = _server.authenticate_begin(creds, user_verification=UV)
    result = client.get_assertion(
        {**options["publicKey"], "extensions": {"hmacGetSecret": {"salt1": salt}}}
    ).get_response(0)
    _server.authenticate_complete(state, creds, result)  # raises on a bad assertion
    return result.client_extension_results.hmac_get_secret.output1


# ---------------------------------------------------------------- YuSeal adapter (docs/TESTING.md)
import base64  # noqa: E402

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def credential_public_key(credential_data: bytes) -> ec.EllipticCurvePublicKey:
    """The YubiKey credential's P-256 public key, for the verifier. VERIFY the COSE key labels on hardware."""
    cose = AttestedCredentialData(credential_data).public_key
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()).public_key()


def _ctap_device():
    """The first YubiKey on USB that supports hmac-secret, as a raw CTAP2 device."""
    for dev in CtapHidDevice.list_devices():
        if "hmac-secret" in Ctap2(dev).info.extensions:
            return dev
    raise RuntimeError("No YubiKey with hmac-secret found on USB")


class RealYubiKey:
    """Same interface as yuseal.SoftYubiKey, backed by the real key over USB.

    UNVERIFIED on hardware: run `python3 tools/yk_probe.py` first.

    MOUSE MODE: nobody touches the key, so by default the assertion and the hmac-secret are asked
    for with user presence OFF (CTAP2 get_assertion option up=false) through the raw Ctap2 API.
    Whether a YubiKey 5 NFC gives the hmac-secret without a touch must be checked on the key. With
    touch=True the old touch path (Fido2Client) is used instead: it works, but needs a touch per
    approval, which breaks "zero input". If neither works, use YK_MODE=hmac-sha1 (RealYubiKeyHmac).

    The YubiKey signs challenge = SHA-256(core) and we return the raw authenticatorData,
    clientDataJSON and signature, which the verifier re-checks. The origin is https://<RP_ID> and
    RP_ID must equal the verifier's service ID (FIDO_RP_ID in .env, same on both).
    """

    def __init__(self, credential_data: bytes | None = None, touch: bool = False):
        self.credential = credential_data
        self.touch = touch

    def register(self, user: str):
        cred, _salt, _secret = enrol(user)  # touches twice; the salt and secret here are discarded
        self.credential = cred
        return cred, credential_public_key(cred)

    def assert_and_secret(self, rp_id: str, challenge: bytes, salt: bytes):
        assert rp_id == RP_ID, "FIDO_RP_ID must equal the verifier's service ID"
        b64 = lambda b: base64.urlsafe_b64encode(bytes(b)).rstrip(b"=").decode()
        if self.touch:
            client = _client()
            creds = [AttestedCredentialData(self.credential)]
            options, _state = _server.authenticate_begin(creds, user_verification=UV, challenge=challenge)
            result = client.get_assertion(
                {**options["publicKey"], "extensions": {"hmacGetSecret": {"salt1": salt}}}).get_response(0)
            assertion = {"authenticator_data": b64(result.response.authenticator_data),
                         "client_data_json": b64(result.response.client_data),
                         "signature": b64(result.response.signature)}
            return assertion, result.client_extension_results.hmac_get_secret.output1
        # No touch: raw CTAP2 with up=false. Build the client data ourselves, as yuseal.SoftYubiKey does.
        client_data = json.dumps({"type": "webauthn.get", "challenge": b64(challenge),
                                  "origin": f"https://{rp_id}"}, sort_keys=True, separators=(",", ":")).encode()
        ctap = Ctap2(_ctap_device())
        cp = ClientPin(ctap)
        key_agreement, shared = cp._get_shared_secret()
        salt_enc = cp.protocol.encrypt(shared, salt)
        salt_auth = cp.protocol.authenticate(shared, salt_enc)
        resp = ctap.get_assertion(
            rp_id, hashlib.sha256(client_data).digest(),
            allow_list=[{"type": "public-key", "id": AttestedCredentialData(self.credential).credential_id}],
            extensions={"hmac-secret": {1: key_agreement, 2: salt_enc, 3: salt_auth, 4: cp.protocol.VERSION}},
            options={"up": False})
        ext = (resp.auth_data.extensions or {}).get("hmac-secret")
        if not ext:
            raise RuntimeError("YubiKey gave no hmac-secret without a touch: use touch=True or YK_MODE=hmac-sha1")
        secret = cp.protocol.decrypt(shared, ext)[:32]
        assertion = {"authenticator_data": b64(bytes(resp.auth_data)), "client_data_json": b64(client_data),
                     "signature": b64(resp.signature)}
        return assertion, secret


class RealYubiKeyHmac:
    """FALLBACK for when FIDO2 will not work without a touch: the YubiKey's HMAC-SHA1
    challenge-response slot, configured WITHOUT touch (tools/setup_yk_hmac.py).

    Same interface as RealYubiKey. It is weaker: there is no public-key signature, so the verifier
    holds the slot's secret (tools/out/yk_hmac_key.json) and checks the response itself. The
    verifier can then fake the YubiKey proof (not the other two), so keep the verifier trusted.
    Needs the `ykman` command (pip install yubikey-manager) and the YubiKey's OTP interface on.
    """

    def __init__(self, slot: int = 2):
        self.slot = slot

    def calc(self, challenge: bytes) -> bytes:
        out = subprocess.run(["ykman", "otp", "calculate", str(self.slot), challenge.hex()],
                             capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        resp = bytes.fromhex(out)
        if len(resp) != 20:
            raise RuntimeError(f"unexpected ykman response {out!r}")
        return resp

    def register(self, user: str):
        return b"hmac-sha1", None  # nothing to register: the slot was programmed by tools/setup_yk_hmac.py

    def assert_and_secret(self, rp_id: str, challenge: bytes, salt: bytes):
        b64 = lambda b: base64.urlsafe_b64encode(bytes(b)).rstrip(b"=").decode()
        proof = {"kind": "hmac-sha1", "response": b64(self.calc(challenge))}
        return proof, hashlib.sha256(b"YuDuino/ykhmac/secret" + self.calc(salt)).digest()


def make_yubikey(credential_data: bytes | None = None):
    """YK_MODE=fido (default) | fido-touch | hmac-sha1."""
    mode = os.environ.get("YK_MODE", "fido")
    if mode == "hmac-sha1":
        return RealYubiKeyHmac(int(os.environ.get("YK_SLOT", "2")))
    return RealYubiKey(credential_data, touch=(mode == "fido-touch"))
