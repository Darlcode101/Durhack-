"""Run on the board with the YubiKey plugged in, BEFORE enrolling:

    python3 tools/yk_probe.py

Tells you which YubiKey mode this key supports without a touch, so you pick the right one:
    fido          FIDO2 assertion AND hmac-secret with user presence off (best)
    fido-touch    works only with a touch (breaks zero input: one tap per approval)
    hmac-sha1     the challenge-response slot, configured without touch (fallback)
It makes a throwaway FIDO2 credential (touch the key ONCE when it blinks) and tries each way.
"""
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "python"))
import yubikey_auth as ya  # noqa: E402
from fido2.ctap2 import Ctap2  # noqa: E402
from fido2.ctap2.pin import ClientPin  # noqa: E402
from fido2.webauthn import AttestedCredentialData  # noqa: E402

print("1. looking for a YubiKey...")
try:
    dev = ya._ctap_device()
except Exception as e:
    print("   FAIL:", e, "\n   Check the hub cable, the udev rule (/dev/hidraw*) and that the key has hmac-secret.")
    dev = None
results = {}
if dev:
    ctap = Ctap2(dev)
    print("   found. extensions:", ctap.info.extensions, "options:", ctap.info.options)
    print("2. creating a throwaway credential: TOUCH THE KEY when it blinks")
    cred, salt, secret = ya.enrol("probe")
    print("   ok (touched path works). hmac-secret with touch: 32 bytes =", len(secret) == 32)
    results["fido-touch"] = True
    cid = AttestedCredentialData(cred).credential_id
    cdh = hashlib.sha256(b"probe").digest()
    allow = [{"type": "public-key", "id": cid}]
    print("3. assertion with user presence OFF (do NOT touch)")
    try:
        r = ctap.get_assertion(ya.RP_ID, cdh, allow_list=allow, options={"up": False})
        print("   ok: UP flag =", bool(r.auth_data.flags & 1))
        results["assertion-no-touch"] = True
    except Exception as e:
        print("   FAIL:", type(e).__name__, e)
    print("4. hmac-secret with user presence OFF (do NOT touch)")
    try:
        yk = ya.RealYubiKey(cred)
        _, s1 = yk.assert_and_secret(ya.RP_ID, hashlib.sha256(b"c").digest(), salt)
        _, s2 = yk.assert_and_secret(ya.RP_ID, hashlib.sha256(b"d").digest(), salt)
        same = s1 == s2 and len(s1) == 32
        print("   ok, same secret each time:", same)
        results["fido"] = same
    except Exception as e:
        print("   FAIL:", type(e).__name__, e)
print("5. HMAC-SHA1 slot 2 (needs tools/setup_yk_hmac.py first)")
try:
    out = subprocess.run(["ykman", "otp", "calculate", "2", "00" * 8], capture_output=True, text=True, timeout=10)
    ok = out.returncode == 0 and len(bytes.fromhex(out.stdout.strip())) == 20
    print("   ok (no touch needed)" if ok else "   FAIL: " + (out.stderr.strip() or out.stdout.strip()))
    results["hmac-sha1"] = ok
except Exception as e:
    print("   FAIL:", type(e).__name__, e, "(pip install yubikey-manager)")
print()
if results.get("fido"):
    print("USE:  python3 app/python/main.py enrol <name>                (default YK_MODE=fido)")
elif results.get("hmac-sha1"):
    print("USE:  python3 app/python/main.py --yk hmac-sha1 enrol <name>")
elif results.get("fido-touch"):
    print("FIDO2 works only with a touch. Set up the HMAC-SHA1 slot (tools/setup_yk_hmac.py) for zero input,")
    print("or demo with:  python3 app/python/main.py --yk fido-touch enrol <name>   (a tap per approval)")
else:
    print("Nothing worked: see the messages above.")
