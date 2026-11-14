# Duress-aware authentication

DurHack hardware track — *sense, analyse and respond to the real world.*

A YubiKey and button PIN prove **who** is logging in. An Arduino UNO Q reads a handheld grip (shake, palm humidity and temperature, grip, sweat) and a USB camera; a rules engine and Gemini judge **whether the person is acting freely**. Under duress the system shows a normal "access granted" screen while silently alerting.

Full plan, schedule and limitations: [docs/PLAN.md](docs/PLAN.md)

## Hardware

Arduino UNO Q · USB camera · USB-C hub with power passthrough · Modulino Thermo, Movement, Buttons (Qwiic chain) · touch sensor (D2) · moisture probe (A0) · YubiKey

## Layout

```
app/
  sketch/sketch.ino     MCU: reads sensors, exposes get_features / clear_pin over Bridge
  python/
    main.py             Linux entry point: capture window → score → respond
    camera.py           USB camera + Haar face count (frames kept in memory only)
    risk_rules.py       offline rules vs personal baseline (always runs)
    fusion_gemini.py    Gemini: frame + sensor summary → structured risk JSON
    responder.py        grant / step-up / decoy grant + silent webhook alert + audit log
    auth_webauthn.py    YubiKey via WebAuthn (stub, Phase 1)
docs/PLAN.md
```

## Setup

1. Install **Arduino App Lab**, update the UNO Q and connect it to Wi-Fi (use a phone hotspot at the venue).
2. In App Lab, create a new app, then copy `app/sketch/` and `app/python/` into it. Install the `Arduino_Modulino` library.
3. `cp .env.example .env` and fill in `GEMINI_API_KEY`, `GEMINI_MODEL`, `ALERT_WEBHOOK_URL`. **Never commit `.env`.**
4. For WebAuthn, open the dashboard through an SSH tunnel so the browser treats it as a secure context:
   ```bash
   ssh -L 8000:localhost:8000 arduino@<board>.local
   ```

On a laptop without the board, `python3 app/python/main.py` runs with fake sensor values.

## Status

Scaffold only — **not yet run on the UNO Q.** Several library calls are marked `VERIFY` in the code; the checklist is in [docs/PLAN.md](docs/PLAN.md#things-to-verify-in-hour-02-code-assumes-these-not-yet-tested-on-hardware).
