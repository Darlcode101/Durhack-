# Plan — Duress-aware authentication (DurHack hardware track)

> Track: *build an intelligent system that can sense, analyse and respond to the real world.*

**One line:** the YubiKey + PIN prove **who** is logging in; sensors, camera and Gemini judge **whether they're acting freely**. If duress is detected, the system looks like it lets them in, but silently raises an alert.

| Verb | What we do |
|---|---|
| Sense | USB camera, Modulino Thermo (temp + humidity), Modulino Movement (shake), Modulino Buttons (PIN), touch, moisture, YubiKey |
| Analyse | Features vs. personal baseline, aggregated and translated by Gemini (the duress calculation); minimal onboard veto |
| Respond | Grant / step-up / decoy-grant + silent alert, LED matrix + dashboard + audit log |

## Hardware

```
USB-C hub with power passthrough (UNO Q has ONE USB-C port)
  ├─ USB camera
  └─ 5V/3A USB-C power supply
        └─► Arduino UNO Q
             ├─ Linux (Qualcomm MPU): python/ — camera, WebAuthn, Gemini, rules, dashboard, alerts
             │        ▲ Bridge (Python polls MCU with Bridge.call)
             └─ MCU (STM32): sketch/ — reads sensors, computes features
                  Qwiic chain: Modulino Thermo → Movement → Buttons
                  D2: touch sensor   A0: moisture probe   (power both from 3.3V)
Laptop browser + YubiKey ──SSH tunnel──► dashboard on the UNO Q
```

**The grip:** one handheld object holding Movement (shake), touch (grip), Thermo (palm temperature and **humidity — a better sweat proxy than the soil probe**) and the moisture probe. Long Qwiic cables to the board.

## Login flow

1. **Enrol (once):** register YubiKey (WebAuthn), set button PIN + secret **duress PIN**, record a 30 s resting baseline.
2. User holds the grip → ~8 s capture window (sensors + camera).
3. Enter PIN on Modulino Buttons (A/B/C sequence). Wrong PIN → denied.
4. Tap YubiKey (WebAuthn).
5. Translate: features (deltas vs baseline) + frame → Gemini, which does the duress calculation → `{duress_score, signals, reasoning}`. Onboard veto: duress PIN, extreme readings or an unplugged sensor force the decoy.
6. Respond: `grant` / `step_up` / `duress` → decoy grant + Discord webhook alert + audit log.

**Rule:** Gemini calculates the verdict; the STM32 makes the final decision and holds the keys. Fail closed: no, late or malformed reply → decoy key. Pinned HTTPS to Google. PIN and YubiKey touch always required; PINs are never sent to Gemini.

## Downloads

**Laptop:** Arduino App Lab · (optional) Arduino IDE 2 + UNO Q core · Git, Python 3.11+ · YubiKey Manager (`ykman`) · Gemini API key from aistudio.google.com · Discord webhook for alerts

**Arduino libraries:** `Arduino_Modulino` (covers Thermo, Movement, Buttons) · `Arduino_RouterBridge`

**Python (`app/python/requirements.txt`):** google-genai, webauthn, fastapi, uvicorn, opencv-python-headless, numpy, requests, python-dotenv

**Bring:** USB-C PD hub + 5V/3A supply · Qwiic cables · breadboard · phone hotspot (venue Wi-Fi sign-in pages won't work on the board)

## Schedule (~24 h)

| Phase | Hours | Done when |
|---|---|---|
| 0. Smoke tests | 0–2 | Board updated + on Wi-Fi; LED matrix demo; camera seen via hub; all 3 Modulinos detected; `ykman info` shows key model; SSH works |
| 1. Data pipes | 2–8 | `get_features` returns real values over Bridge; camera frames; WebAuthn register + login end to end |
| 2. Analyse | 8–14 | Baseline enrolment; rules tuned on real data; Gemini call returning valid JSON; fallback on timeout |
| 3. Respond | 14–20 | LED matrix states, decoy mode, webhook alert, dashboard with live charts + audit log |
| 4. Polish | 20–24 | Grip enclosure, wiring diagram, README, rehearse calm vs coerced demo, backup video |

Team of 4: (1) MCU + sensors (2) Linux, camera, Gemini (3) auth + dashboard (4) enclosure, demo, pitch.

## Things to verify in hour 0–2 (code assumes these; not yet tested on hardware)

- [ ] Modulino Qwiic port on UNO Q: does `Modulino.begin()` find the chain, or does it need `Wire1`?
- [ ] `ModulinoMovement::getX/getY/getZ` and `update()` names
- [ ] `ModulinoButtons` API: `update()` + `isPressed(i)`, or press callbacks?
- [ ] `Bridge.provide` returning a `String` arrives in Python as a `str`
- [ ] App Lab Python can `pip install` our requirements (otherwise run Python over SSH)
- [ ] Camera index on the hub (`cv2.VideoCapture(0)`)
- [ ] Current Gemini Flash model name → `GEMINI_MODEL` in `.env`
- [ ] YubiKey model: blue Security Key series = FIDO2 only (no OTP fallback)

## Limitations and risks

**Hardware**
- One USB-C port: hub is mandatory; weak power → random resets mid-demo.
- 3.3V logic: power analog sensors from 3.3V so outputs stay in ADC range.
- Soil moisture probe ≠ GSR sensor; use deltas only. Thermo humidity near the palm is likely the better sweat signal.
- Skin temperature changes over minutes — weak in an 8 s window; better as a "live hand present" check.
- 2 GB RAM: keep on-board vision light (Haar face count); heavy reasoning goes to Gemini.

**YubiKey**
- WebAuthn needs HTTPS or `localhost` → use `ssh -L 8000:localhost:8000 arduino@<board>.local`, open `http://localhost:8000`.
- Direct USB use on the UNO Q (python-fido2) is a stretch goal; App Lab's container may block USB access.

**Gemini**
- 1–5 s latency, needs network, free-tier rate limits → call once per approval; fail closed to the decoy if it doesn't answer in time.
- Prompt injection via the camera (a sign saying "approve") → system prompt treats image text as untrusted, fixed JSON schema, a malformed reply fails closed, and Gemini can't approve without the PIN and YubiKey touch.
- Non-deterministic → temperature 0, thresholds not single yes/no.

**Core problem**
- Stress ≠ duress (late, cold, coffee). False positives → soft responses only (step-up / silent alert), never hard lockout.
- The explicit duress PIN is the most reliable signal (as in real alarm panels and banks); sensors + AI back it up when the victim can't safely enter it.
- A calm, informed attacker beats physiological checks. Say so in the threat model.

**Privacy and ethics**
- Free-tier Gemini data may be used by Google to improve products → only consenting teammates on camera; frames never stored.
- Emotion recognition is legally sensitive (EU AI Act restricts it at work) → frame as "context risk scoring".
