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
import os

from fido2.client import DefaultClientDataCollector, Fido2Client, UserInteraction
from fido2.ctap2.extensions import HmacSecretExtension
from fido2.hid import CtapHidDevice
from fido2.server import Fido2Server
from fido2.webauthn import AttestedCredentialData

RP_ID = os.environ.get("FIDO_RP_ID", "duress-auth.local")
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


# ---------------------------------------------------------------- YuSeal adapter (docs/BUILD-FLOW.md, step 4)
import base64  # noqa: E402

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def credential_public_key(credential_data: bytes) -> ec.EllipticCurvePublicKey:
    """The YubiKey credential's P-256 public key, for the guardian. VERIFY the COSE key labels on hardware."""
    cose = AttestedCredentialData(credential_data).public_key
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()).public_key()


class RealYubiKey:
    """Same interface as yuseal.SoftYubiKey, backed by the real key over USB.

    UNVERIFIED on hardware. The YubiKey must sign challenge = SHA-256(core) and return the raw
    authenticatorData, clientDataJSON and signature, which the guardian re-checks. python-fido2's
    get_assertion() takes the challenge in the options; the origin must be https://<RP_ID> and
    RP_ID must equal the guardian's service ID (FIDO_RP_ID in .env, same on both).

    MOUSE MODE: nobody touches the key, so the assertion must be made with user presence OFF
    (CTAP2 get_assertion option up=false). python-fido2's Fido2Client does not expose that, so on
    the board this likely needs Ctap2(dev).get_assertion(..., options={"up": False}) directly,
    and whether the hmac-secret is still returned without a touch must be checked on the
    YubiKey 5 NFC. If the key insists on a touch, the YubiKey is a pure presence prompt and
    this design needs a rethink: say so rather than hide it.
    """

    def __init__(self, credential_data: bytes | None = None):
        self.credential = credential_data

    def register(self, user: str):
        cred, _salt, _secret = enrol(user)  # touches twice; the salt and secret here are discarded
        self.credential = cred
        return cred, credential_public_key(cred)

    def assert_and_secret(self, rp_id: str, challenge: bytes, salt: bytes):
        assert rp_id == RP_ID, "FIDO_RP_ID must equal the guardian's service ID"
        client = _client()
        creds = [AttestedCredentialData(self.credential)]
        options, _state = _server.authenticate_begin(creds, user_verification=UV, challenge=challenge)
        result = client.get_assertion(
            {**options["publicKey"], "extensions": {"hmacGetSecret": {"salt1": salt}}}).get_response(0)
        b64 = lambda b: base64.urlsafe_b64encode(bytes(b)).rstrip(b"=").decode()
        assertion = {"authenticator_data": b64(result.response.authenticator_data),
                     "client_data_json": b64(result.response.client_data),
                     "signature": b64(result.response.signature)}
        return assertion, result.client_extension_results.hmac_get_secret.output1
