"""Linux-side entry point. Everything runs on the UNO Q.

    python3 main.py enrol <user>                     once: YubiKey, PIN check, post-quantum key, guardian
    python3 main.py approve <user> '<request json>'  one approval, e.g.
        '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1..."}'

Run over SSH on the board. The PIN is typed on the Modulino Buttons, never on this keyboard.
See docs/BUILD-FLOW.md. (The earlier PIN-on-Linux flow is kept in pq_keystore.py / verifier.py
for reference only.)
"""
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import requests

import approve as ap
import camera
import yuseal as ys
from fusion_gemini import gemini_score
from yubikey_auth import RealYubiKey

try:
    from arduino.app_utils import Bridge  # provided inside App Lab apps
except ImportError:
    sys.exit("arduino.app_utils not found: run this inside App Lab on the UNO Q. "
             "For a laptop demo without a board, run the tests: python3 -m unittest test_yuseal")

RP_ID = os.environ.get("FIDO_RP_ID", "guardian.yuduino.local")
GUARDIAN = os.environ.get("GUARDIAN_URL", "http://localhost:8000")
STATE_PATH = os.environ.get("DEVICE_STATE", os.path.join(os.path.dirname(__file__), "device.json"))
ADDRESS_BOOK = json.loads(os.environ.get("ADDRESS_BOOK", "{}"))   # must match the guardian's


class _Bridge:
    def call(self, name, *args):
        return str(Bridge.call(name, *args))  # VERIFY: argument passing and return types on the UNO Q


def _guardian():
    return ap.HttpGuardian(lambda path, body: requests.post(GUARDIAN + path, json=body, timeout=5).json())


def gemini_fn(window):
    jpeg, faces = camera.grab()
    if not jpeg or not window:
        return None
    last = {k: v for k, v in window[-1].items() if k not in ("state", "pin_count")}
    return gemini_score(jpeg, {**last, "face_count": faces, "readings": len(window)})


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("enrol", "approve"):
        sys.exit(__doc__)
    state = ap.DeviceState(STATE_PATH)
    if sys.argv[1] == "enrol":
        user = sys.argv[2]
        body = ap.enrol(bridge=_Bridge(), yk=RealYubiKey(), guardian=_guardian(), state=state,
                        user=user, device="unoq-1", rp_id=RP_ID)
        body["k_tag"] = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "tools", "out",
                                                    "guardian_tag_key.json")))["k_tag"]
        print(_guardian().enrol(user, body))
    else:
        yk = RealYubiKey(ys.unb64(state.data["credential"]))
        out = ap.approve(bridge=_Bridge(), yk=yk, guardian=_guardian(), state=state,
                         request=json.loads(sys.argv[3]), address_book=ADDRESS_BOOK, rp_id=RP_ID,
                         gemini_fn=gemini_fn)
        print("Requester is told:", out["public"])  # same for a normal and a duress approval


if __name__ == "__main__":
    main()
