# Runs INSIDE the App Lab app (copy to <app>/python/main.py).
# 1. Polls the STM32 over Bridge and writes the latest reading to <app>/live/features.json,
#    which the dashboard (running outside the container) reads.
# 2. Serves Bridge calls for app/python/main.py, which runs OUTSIDE the container (it needs the
#    YubiKey over USB): main.py writes live/rpc/<id>.req ({"name":..., "args":[...]}) and this
#    loop answers in live/rpc/<id>.res ({"ok":true,"result":"..."} or {"ok":false,"error":"..."}).
# Stdlib only.
from arduino.app_utils import *
import glob
import json
import os
import time

OUT_DIR = "/app/live"          # /app is the app folder, mounted from the host
RPC_DIR = os.path.join(OUT_DIR, "rpc")
os.makedirs(RPC_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "features.json")
last_features = 0.0


def write_features():
    global last_features
    if time.time() - last_features < 0.2:
        return
    last_features = time.time()
    try:
        raw = Bridge.call("get_features")
        data = json.loads(raw.replace("nan", "null"))
        data["t"] = time.time()
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, OUT)   # atomic: the dashboard never reads half a file
    except Exception as e:
        print("relay error:", type(e).__name__, e, flush=True)


def serve_rpc():
    for req in sorted(glob.glob(os.path.join(RPC_DIR, "*.req"))):
        res = req[:-4] + ".res"
        try:
            with open(req) as f:
                call = json.load(f)
            out = {"ok": True, "result": str(Bridge.call(call["name"], *call.get("args", [])))}
        except Exception as e:
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            tmp = res + ".tmp"
            with open(tmp, "w") as f:
                json.dump(out, f)
            os.replace(tmp, res)
            os.remove(req)
        except OSError:
            pass


def loop():
    time.sleep(0.03)
    serve_rpc()          # approvals first: the click window is only 1.5 s
    write_features()


App.run(user_loop=loop)
