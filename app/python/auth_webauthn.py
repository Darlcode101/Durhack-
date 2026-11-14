"""YubiKey via WebAuthn (py_webauthn). STUB — to be filled in during Phase 1.

The browser (on the laptop, YubiKey plugged into the laptop) does the WebAuthn
ceremony; this module issues challenges and verifies responses.

WebAuthn only works in a secure context. Open the dashboard through an SSH tunnel:
    ssh -L 8000:localhost:8000 arduino@<board>.local
then browse to http://localhost:8000 (RP ID = "localhost").

Fallback if this blocks you: Yubico OTP typed into a form field, validated with YubiCloud.
Note the blue "Security Key" series has no OTP — check with `ykman info`.
"""
import os

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)

RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")
RP_NAME = "Duress-aware login"

# In-memory store is fine for a hackathon demo. user -> {"credential_id", "public_key", "sign_count", "pin", "duress_pin", "baseline"}
USERS: dict[str, dict] = {}
_pending_challenges: dict[str, bytes] = {}


def start_registration(username: str):
    opts = generate_registration_options(rp_id=RP_ID, rp_name=RP_NAME, user_name=username)
    _pending_challenges[username] = opts.challenge
    return opts  # serialise with webauthn.options_to_json(opts) for the browser


def finish_registration(username: str, credential_json: str):
    v = verify_registration_response(
        credential=credential_json,
        expected_challenge=_pending_challenges.pop(username),
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
    )
    USERS.setdefault(username, {}).update(
        credential_id=v.credential_id, public_key=v.credential_public_key, sign_count=v.sign_count
    )


def start_login(username: str):
    # TODO: pass allow_credentials for this user's credential_id
    opts = generate_authentication_options(rp_id=RP_ID)
    _pending_challenges[username] = opts.challenge
    return opts


def finish_login(username: str, credential_json: str) -> bool:
    u = USERS[username]
    v = verify_authentication_response(
        credential=credential_json,
        expected_challenge=_pending_challenges.pop(username),
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
        credential_public_key=u["public_key"],
        credential_current_sign_count=u["sign_count"],
    )
    u["sign_count"] = v.new_sign_count
    return True
