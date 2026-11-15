"""Calls the STM32 from Linux: Bridge directly inside the App Lab container, else through the
file relay (app/dashboard/applab_relay.py). Shared by main.py and the dashboard."""
import json
import os
import sys
import time

try:
    from arduino.app_utils import Bridge  # only inside the App Lab container
except ImportError:
    Bridge = None

LIVE_DIR = os.environ.get("APPLAB_LIVE", os.path.expanduser("~/ArduinoApps/durhack-sensors/live"))


class StmBridge:
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


