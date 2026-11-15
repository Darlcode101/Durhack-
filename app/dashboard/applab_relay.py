# Runs INSIDE the App Lab app (copy to <app>/python/main.py).
# Polls the STM32 over Bridge and writes the latest reading to <app>/live/features.json,
# which the dashboard (running outside the container) reads. Stdlib only.
from arduino.app_utils import *
import json
import os
import time

OUT_DIR = "/app/live"          # /app is the app folder, mounted from the host
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "features.json")


def loop():
    time.sleep(0.2)
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


App.run(user_loop=loop)
