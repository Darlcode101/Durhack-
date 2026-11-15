"""Fallback setup, only if tools/yk_probe.py says FIDO2 needs a touch. Run ONCE on the board
(where the YubiKey is plugged in; tools/out/ must then also be on the guardian's side):

    pip install yubikey-manager
    python3 tools/setup_yk_hmac.py

It programs the YubiKey's slot 2 with a random HMAC-SHA1 challenge-response key that needs NO touch
(this REPLACES whatever is in slot 2: if you use it for something, pass --slot 1 only if slot 1 is free)
and writes tools/out/yk_hmac_key.json (secret, gitignored) for the guardian. Then:

    python3 app/python/main.py --yk hmac-sha1 enrol <name>

Weaker than FIDO2: there is no public-key signature, so the guardian holds this key and could fake
the YubiKey proof (but not the STM32 tag or the ML-DSA signature). Delete tools/out/ afterwards
from the laptop once it is on the guardian.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "python"))
import yuseal as ys  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--slot", type=int, choices=(1, 2), default=2)
a = p.parse_args()
key = os.urandom(20)
# No --touch flag: challenge-response runs without a tap.
subprocess.run(["ykman", "otp", "chalresp", "--force", str(a.slot), key.hex()], check=True)
root = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(root, exist_ok=True)
with open(os.path.join(root, "yk_hmac_key.json"), "w") as f:
    os.fchmod(f.fileno(), 0o600)
    json.dump({"yk_hmac_key": ys.b64(key), "slot": a.slot}, f)
print(f"Programmed slot {a.slot} (no touch) and wrote tools/out/yk_hmac_key.json")
print("Test: ykman otp calculate", a.slot, "00" * 8, " -> 40 hex characters, no blinking")
