"""Linux-side entry point. Everything runs here on the UNO Q.

    python3 main.py enrol <user>   # once: baseline, button PINs, YubiKey, post-quantum keys
    python3 main.py login <user>   # repeat: sense → YubiKey → score → signed token

Run over SSH on the board (enrol prompts on the terminal).
"""
import json
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import camera
import pq_keystore
import yubikey_auth
from fusion_gemini import gemini_score
from responder import act, decide
from risk_rules import rules_score

try:
    from arduino.app_utils import Bridge  # provided inside App Lab apps
except ImportError:
    Bridge = None
    print("[main] arduino.app_utils not found — running without MCU (fake sensors, PIN typed on keyboard)")


def read_features() -> dict:
    if Bridge is None:
        return {"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "touch": 1, "moisture": 400, "pin_entry": ""}
    return json.loads(Bridge.call("get_features"))


def clear_pin():
    if Bridge is not None:
        Bridge.call("clear_pin")


def read_pin(prompt: str) -> str:
    if Bridge is None:
        return input(prompt + " (type e.g. ABCA): ").strip().upper()
    clear_pin()
    input(prompt + " on the buttons, then press Enter… ")
    pin = read_features()["pin_entry"]
    clear_pin()
    return pin


def capture_window(seconds: float) -> dict:
    """Average sensor features over a window; peak shake matters more than mean."""
    samples = []
    end = time.time() + seconds
    while time.time() < end:
        samples.append(read_features())
        time.sleep(0.1)
    avg = {k: sum(s[k] for s in samples) / len(samples) for k in ("temp_c", "humidity", "moisture")}
    avg["shake_rms"] = max(s["shake_rms"] for s in samples)
    avg["touch"] = samples[-1]["touch"]
    avg["pin_entry"] = samples[-1]["pin_entry"]
    return avg


def enrol(username: str):
    input("Hold the grip calmly for 30 s to record your baseline. Press Enter to start… ")
    baseline = capture_window(30)
    baseline.pop("pin_entry")
    pin = read_pin("Enter your normal PIN")
    duress_pin = read_pin("Enter your secret duress PIN")
    if not pin or not duress_pin or pin == duress_pin:
        sys.exit("PINs must be non-empty and different.")

    cred, salt, secret = yubikey_auth.enrol(username)  # touch the YubiKey twice
    public_keys = pq_keystore.create_user(username, cred, salt, secret, pin, duress_pin, baseline)
    del secret
    with open("verifier_keys.json", "w") as f:  # public keys only — give these to the verifier
        json.dump({username: public_keys}, f, indent=2)
    print(f"Enrolled {username}. Public keys written to verifier_keys.json")


def attempt_login(username: str) -> tuple[str, dict | None]:
    """Returns (what the screen shows, signed token or None)."""
    entry = pq_keystore.get_user(username)
    if entry is None:
        return "denied", None

    print("Hold the grip and enter your PIN on the buttons…")
    features = capture_window(8)
    pin = features["pin_entry"] if Bridge is not None else read_pin("PIN")
    clear_pin()
    role = pq_keystore.check_pin(entry, pin)
    if role is None:
        return "denied", None

    try:
        secret = yubikey_auth.login(
            pq_keystore._unb64(entry["credential"]), pq_keystore._unb64(entry["hmac_salt"])
        )
    except Exception as e:
        print(f"[yubikey] login failed: {e}")
        return "denied", None

    jpeg, faces = camera.grab()
    rules = rules_score(features, entry["baseline"], faces, explicit_duress=(role == "duress"))
    summary = {k: v for k, v in features.items() if k != "pin_entry"}  # never send PINs to the cloud
    summary.update(face_count=faces, baseline=entry["baseline"])
    gem = gemini_score(jpeg, summary) if jpeg else None
    decision = decide(rules, gem)
    print(json.dumps(decision, indent=2))

    token = None
    if decision["outcome"] in ("grant", "duress"):
        sign_with = "duress" if decision["outcome"] == "duress" else "normal"
        token = pq_keystore.issue_token(username, entry, secret, sign_with)
    del secret
    return act(username, decision), token


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("enrol", "login"):
        sys.exit(__doc__)
    cmd, user = sys.argv[1], sys.argv[2]
    if cmd == "enrol":
        enrol(user)
    else:
        while True:
            input("\nPress Enter to start a login… ")
            shown, token = attempt_login(user)
            print("Screen shows:", shown)
            if token:
                print("Token:", json.dumps(token)[:120], "…")
