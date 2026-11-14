"""Linux side entry point (runs on the UNO Q's Qualcomm MPU).

Phase-1 skeleton: polls MCU features over Bridge, grabs a frame, scores risk,
and prints a decision. The web dashboard / WebAuthn routes get added on top.
"""
import json
import time

from dotenv import load_dotenv

import camera
from fusion_gemini import gemini_score
from responder import act, decide
from risk_rules import rules_score

load_dotenv()

try:
    from arduino.app_utils import Bridge  # provided inside App Lab apps
except ImportError:
    Bridge = None
    print("[main] arduino.app_utils not found — running without MCU (laptop dev mode)")


def read_features() -> dict:
    if Bridge is None:
        return {"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "touch": 1, "moisture": 400, "pin_entry": ""}
    return json.loads(Bridge.call("get_features"))


def capture_window(seconds: float = 8.0) -> dict:
    """Average sensor features over the login window."""
    samples = []
    end = time.time() + seconds
    while time.time() < end:
        samples.append(read_features())
        time.sleep(0.1)
    avg = {k: sum(s[k] for s in samples) / len(samples) for k in ("temp_c", "humidity", "shake_rms", "moisture")}
    avg["shake_rms"] = max(s["shake_rms"] for s in samples)  # peak shake matters more than mean
    avg["touch"] = samples[-1]["touch"]
    avg["pin_entry"] = samples[-1]["pin_entry"]
    return avg


def attempt_login(username: str, user: dict) -> str:
    # TODO Phase 1: require a successful WebAuthn finish_login() before this runs.
    features = capture_window()
    if features["pin_entry"] not in (user["pin"], user["duress_pin"]):
        if Bridge is not None:
            Bridge.call("clear_pin")
        return "denied"
    jpeg, faces = camera.grab()
    rules = rules_score(features, user["baseline"], faces, features["pin_entry"], user)
    summary = {**features, "face_count": faces, "baseline": user["baseline"]}
    summary.pop("pin_entry")  # never send PINs to the cloud
    gem = gemini_score(jpeg, summary) if jpeg else None
    decision = decide(rules, gem)
    print(json.dumps(decision, indent=2))
    if Bridge is not None:
        Bridge.call("clear_pin")
    return act(username, decision)


if __name__ == "__main__":
    demo_user = {
        "pin": "ABCA",
        "duress_pin": "ABCC",
        "baseline": {"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "moisture": 400},
    }
    while True:
        input("Hold the grip, enter PIN on the buttons, then press Enter... ")
        print("UI shows:", attempt_login("demo", demo_user))
