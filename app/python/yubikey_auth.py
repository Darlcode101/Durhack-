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
UV = "discouraged"  # touch only; the Modulino button PIN is the knowledge factor

_server = Fido2Server({"id": RP_ID, "name": "Duress-aware login"}, attestation="none")


class _Prompt(UserInteraction):
    def prompt_up(self):
        print("[yubikey] touch your YubiKey…")  # TODO: also show on the LED matrix

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
