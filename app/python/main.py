"""Linux-side entry point. Everything runs on the UNO Q.

    python3 main.py [--yk MODE] enrol <user>         once: YubiKey, one click, post-quantum key, guardian
    python3 main.py approve <user> '<request json>'  one approval, e.g.
        '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1..."}'

--yk MODE (or env YK_MODE): fido (default, no touch), fido-touch, or hmac-sha1 (fallback, see
tools/setup_yk_hmac.py). Run `python3 tools/yk_probe.py` first to see which one your key allows.

Run over SSH on the board, with the App Lab sensor app running (it carries the STM32 calls via
app/dashboard/applab_relay.py). There is nothing to type or press but the mouse's own click: it
works like any mouse. See docs/BUILD-FLOW.md. (The earlier PIN-on-Linux flow is kept in
pq_keystore.py / verifier.py for reference only.)
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
from yubikey_auth import make_yubikey

try:
    from arduino.app_utils import Bridge  # only inside the App Lab container
except ImportError:
    Bridge = None

RP_ID = os.environ.get("FIDO_RP_ID", "guardian.yuduino.local")
GUARDIAN = os.environ.get("GUARDIAN_URL", "http://localhost:8000")
STATE_PATH = os.environ.get("DEVICE_STATE", os.path.join(os.path.dirname(__file__), "device.json"))
ADDRESS_BOOK = json.loads(os.environ.get("ADDRESS_BOOK", "{}"))   # must match the guardian's


LIVE_DIR = os.environ.get("APPLAB_LIVE", os.path.expanduser("~/ArduinoApps/durhack-sensors/live"))


class _Bridge:
    """Calls the STM32. Inside the App Lab container it uses Bridge directly. Outside (where the
    YubiKey is reachable) it goes through app/dashboard/applab_relay.py, which must be running."""

    def call(self, name, *args):
        if Bridge is not None:
            return str(Bridge.call(name, *args))  # VERIFY: argument passing and return types on the UNO Q
        rpc = os.path.join(LIVE_DIR, "rpc")
        if not os.path.isdir(rpc):
            sys.exit(f"{rpc} not found: start the App Lab sensor app (applab_relay.py) first, "
                     "or set APPLAB_LIVE to its live/ folder")
        rid = f"{time.time_ns()}"
        req, res = os.path.join(rpc, rid + ".req"), os.path.join(rpc, rid + ".res")
        with open(req + ".tmp", "w") as f:
            json.dump({"name": name, "args": list(args)}, f)
        os.replace(req + ".tmp", req)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if os.path.exists(res):
                with open(res) as f:
                    out = json.load(f)
                os.remove(res)
                if not out["ok"]:
                    raise RuntimeError(out["error"])
                return out["result"]
            time.sleep(0.02)
        raise RuntimeError(f"no answer from the relay for {name}: is the App Lab app running?")


def _guardian():
    return ap.HttpGuardian(lambda path, body: requests.post(GUARDIAN + path, json=body, timeout=5).json())


def gemini_fn(window):
    """The transaction's duress check. Prefer the live dashboard's (two learned baselines from Tiger,
    the camera tie-break, Gemini only when the sensors are unsure); it returns fusion_gemini's format.
    Falls back to a direct Gemini call if the dashboard isn't running."""
    try:
        r = requests.post(os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8080") + "/api/assess",
                          params={"label": "approval", "seconds": 2}, timeout=20)
        if r.status_code == 200 and "duress_score" in r.json():
            return r.json()
    except Exception:
        pass
    jpeg, faces = camera.grab()
    if not jpeg or not window:
        return None
    last = {k: v for k, v in window[-1].items() if k != "state"}
    return gemini_score(jpeg, {**last, "face_count": faces, "readings": len(window)})


def main():
    argv = sys.argv[1:]
    if "--yk" in argv:  # --yk fido (default) | fido-touch | hmac-sha1
        i = argv.index("--yk")
        os.environ["YK_MODE"] = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) < 2 or argv[0] not in ("enrol", "approve"):
        sys.exit(__doc__)
    state = ap.DeviceState(STATE_PATH)
    tools_out = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "out")
    if argv[0] == "enrol":
        user = argv[1]
        body = ap.enrol(bridge=_Bridge(), yk=make_yubikey(), guardian=_guardian(), state=state,
                        user=user, device="unoq-1", rp_id=RP_ID)
        body["k_tag"] = json.load(open(os.path.join(tools_out, "guardian_tag_key.json")))["k_tag"]
        if os.environ.get("YK_MODE") == "hmac-sha1":
            body["yk_hmac_key"] = json.load(open(os.path.join(tools_out, "yk_hmac_key.json")))["yk_hmac_key"]
        print(_guardian().enrol(user, body))
    else:
        yk = make_yubikey(ys.unb64(state.data["credential"]))
        out = ap.approve(bridge=_Bridge(), yk=yk, guardian=_guardian(), state=state,
                         request=json.loads(argv[2]), address_book=ADDRESS_BOOK, rp_id=RP_ID,
                         gemini_fn=gemini_fn)
        print("Requester is told:", out["public"])  # same for a normal and a duress approval


if __name__ == "__main__":
    main()
