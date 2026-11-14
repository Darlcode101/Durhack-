# Duress-aware, post-quantum authentication

DurHack hardware track — *sense, analyse and respond to the real world.*

Everything runs on an **Arduino UNO Q**. A YubiKey plugged into the board only creates key material; the UNO Q is the only device that stores keys, protected with post-quantum cryptography (ML-DSA-65 + AES-256). A handheld grip (shake, palm humidity and temperature, grip, sweat) and a USB camera feed a rules engine and Gemini, which judge **whether the person is acting freely**. Under duress the system shows a normal "access granted" screen but signs the access token with a separate duress key, so the verifier can raise a silent alarm.

Full plan, schedule and limitations: [docs/PLAN.md](docs/PLAN.md)

## Hardware

Arduino UNO Q · USB-C hub with power passthrough (camera + YubiKey + power) · USB camera · YubiKey with FIDO2 · Modulino Thermo, Movement, Buttons (Qwiic chain) · touch sensor (D2) · moisture probe (A0)

## Layout

```
app/
  sketch/sketch.ino     MCU: reads sensors, exposes get_features / clear_pin over Bridge
  python/
    main.py             entry point: `enrol <user>` and `login <user>`
    yubikey_auth.py     YubiKey over USB (CTAP2): credential + hmac-secret, verified on the board
    pq_keystore.py      KEK from YubiKey, encrypted ML-DSA keys, PIN check, token signing
    verifier.py         demo "door": checks tokens with public keys, spots duress tokens
    camera.py           USB camera + Haar face count (frames kept in memory only)
    risk_rules.py       offline rules vs personal baseline (always runs)
    fusion_gemini.py    Gemini: frame + sensor summary → structured risk JSON
    responder.py        grant / step-up / duress: audit log + silent webhook alert
docs/PLAN.md
```

## Setup (on the UNO Q)

1. Install **Arduino App Lab** on your laptop, update the UNO Q and connect it to Wi-Fi (use a phone hotspot at the venue).
2. In App Lab, create a new app, copy `app/sketch/` into it and install the `Arduino_Modulino` library. Run it so the MCU serves sensor data.
3. SSH into the board and build **liboqs** (takes a while, start it early):
   ```bash
   sudo apt install -y cmake ninja-build libssl-dev git
   ```
   ```bash
   git clone --depth 1 https://github.com/open-quantum-safe/liboqs && cmake -S liboqs -B liboqs/build -GNinja -DBUILD_SHARED_LIBS=ON && sudo cmake --build liboqs/build --target install
   ```
4. Install the Python packages: `pip install -r app/python/requirements.txt`
5. Let your user talk to the YubiKey over USB (`/dev/hidraw*`): add a udev rule for Yubico devices, or run as root while testing.
6. `cp .env.example .env` and fill in `GEMINI_API_KEY`, `GEMINI_MODEL`, `ALERT_WEBHOOK_URL`. **Never commit `.env`.**
7. Enrol once, then log in:
   ```bash
   python3 app/python/main.py enrol alice
   ```
   ```bash
   python3 app/python/main.py login alice
   ```

`keystore.json` (encrypted keys) and `verifier_keys.json` (public keys) are created on the board and are gitignored.

## Status

**Not yet run on the UNO Q.** Several library calls are marked `VERIFY` in the code; the checklist is in [docs/PLAN.md](docs/PLAN.md#things-to-verify-in-hour-02-not-yet-tested-on-hardware).
