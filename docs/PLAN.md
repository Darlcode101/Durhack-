# Plan — Duress-aware, post-quantum authentication (DurHack hardware track)

> **Historical (DurHack working doc).** Written during the hackathon. Parts describe the earlier PIN-and-LED-matrix design, Gemini/Tiger Data, or add-ons we didn't build (ElevenLabs, Solana, MongoDB). The final design, as presented, is in the [README](../README.md), the [overview](YuDuino-Overview.md) and the [pitch deck](../presentation/YuDuino-DurHack-2026-pitch.pdf).

> Track: *build an intelligent system that can sense, analyse and respond to the real world.*
>
> The schedule below is superseded by the wave-by-wave **[prototype and development plan](DEV-PLAN.md)**.

**One line:** everything runs on the Arduino UNO Q. The YubiKey only creates key material; the UNO Q is the only device that stores keys, and it protects them with post-quantum cryptography. Sensors, camera and the on-device Edge Impulse model judge **whether the person is acting freely**. Under duress the system looks like it lets them in, but silently raises an alert.

| Verb | What we do |
|---|---|
| Sense | USB camera, Modulino Thermo (temp + humidity), Modulino Movement (shake), Modulino Buttons (PIN), touch, moisture, YubiKey |
| Analyse | On the UNO Q: features vs. personal baseline, aggregated and translated by the on-device Edge Impulse model (the duress calculation) |
| Respond | On the UNO Q: post-quantum signed access token / step-up / duress token + silent alert, LED matrix + audit log |

## Who does what

| Device | Role |
|---|---|
| **YubiKey** | Creates its FIDO2 credential and a 32-byte secret (`hmac-secret`) when touched. Its private key never leaves it. Does nothing else. |
| **UNO Q (Linux side)** | All processing: talks to the YubiKey, derives keys, generates and stores the post-quantum keys, runs camera, the Edge Impulse model, decision, alerts. **The only device that stores keys.** |
| **UNO Q (MCU side)** | Reads sensors, computes features, LED matrix. |
| **Edge Impulse model (on the board)** | Does the duress calculation: gets the feature vector, returns the verdict. A generic model, personalised on the device against the user's own per-hour baseline (which never leaves the device). Never sees keys, PINs or tokens. Fails closed: no model or a malformed output → duress key. |
| **Laptop** | Not in the login path. Optional: view the dashboard. |

## Hardware

```
USB-C hub with power passthrough (UNO Q has ONE USB-C port)
  ├─ USB camera
  ├─ YubiKey
  └─ 5V/3A USB-C power supply
        └─► Arduino UNO Q
             ├─ Linux (Qualcomm MPU): python/ — YubiKey (CTAP2), key derivation, post-quantum
             │    keys + encrypted key store, camera, model, decision, alerts, dashboard
             │        ▲ Bridge (Python polls MCU with Bridge.call)
             └─ MCU (STM32): sketch/ — reads sensors, computes features, LED matrix
                  Qwiic chain: Modulino Thermo → Movement → Buttons
                  D2: touch sensor   A1: moisture probe   (power both from 3.3V)
```

**The grip:** one handheld object holding Movement (shake), touch (grip), Thermo (palm temperature and **humidity — a better sweat proxy than the soil probe**) and the moisture probe. Long Qwiic cables to the board.

## Key design

**Enrolment (once per user, on the UNO Q):**
1. UNO Q asks the YubiKey to create a FIDO2 credential with the `hmac-secret` extension (user touches the key; the Modulino button PIN is the knowledge factor). The YubiKey's private key is generated inside it and never leaves.
2. UNO Q asks the YubiKey for its `hmac-secret` output for a random salt → 32-byte secret → HKDF-SHA-256 → 256-bit **key-encryption key (KEK)**. The KEK only ever exists in RAM.
3. UNO Q generates two **ML-DSA-65** signing key pairs (NIST FIPS 204, post-quantum): a **normal key** and a **duress key**.
4. UNO Q encrypts both private keys with **AES-256-GCM** under the KEK and stores only the ciphertext, salt and credential ID on its own storage.
5. The two public keys go to whatever checks access (the "door" / demo verifier). Public keys aren't secret.

**Login:**
1. Hold the grip → ~8 s sensor + camera window.
2. Enter PIN on Modulino Buttons (A/B/C sequence). Wrong PIN → denied.
3. Touch the YubiKey. UNO Q checks the assertion against the stored credential, gets the `hmac-secret` output, rebuilds the KEK, decrypts the ML-DSA keys in RAM.
4. Translate: features (deltas vs baseline) → the on-device Edge Impulse model, which does the duress calculation → `{duress_score, signals, reasoning}`. Fail closed: no model or a malformed output → duress. The duress PIN goes straight to the duress key.
5. Respond:
   - `grant` → sign an access token (user, time, nonce) with the **normal** key.
   - `step_up` → no token, ask for another check.
   - `duress` → sign with the **duress** key. The token looks valid to an attacker; the verifier recognises the duress key and silently alerts (plus Discord webhook + audit log on the UNO Q).
6. Wipe the KEK and decrypted keys from memory.

**Why this is post-quantum:** access tokens are ML-DSA signatures; keys at rest are AES-256 under a 256-bit KEK (quantum attacks only halve symmetric strength, leaving ~128-bit). Stealing the stored files without the YubiKey gives nothing usable.

**Rule:** the Edge Impulse model alone calculates the verdict, on the board; there is no cloud call. PIN and YubiKey touch always required.

_Considered and dropped: Alex's offline rules engine as a fallback (final score = max(rules, model)). Jonah chose to keep the prototype simple, with the model alone deciding and failing closed._

## Downloads

**Laptop:** Arduino App Lab · (optional) Arduino IDE 2 + UNO Q core · Git, Python 3.11+ · YubiKey Manager (`ykman`: check model, set FIDO2 PIN) · Discord webhook for alerts

**Arduino libraries:** `Arduino_Modulino` (covers Thermo, Movement, Buttons) · `Arduino_RouterBridge`

**On the UNO Q (Linux side):**
- `fido2` (python-fido2) — talks CTAP2 to the YubiKey over USB, incl. `hmac-secret`
- `liboqs` (C, build with CMake on the board) + `liboqs-python` — ML-DSA / ML-KEM
- `cryptography` — HKDF, AES-256-GCM
- `opencv-python-headless`, `numpy`, `requests`, `python-dotenv`, `fastapi` + `uvicorn` (dashboard)

**Bring:** USB-C PD hub with ≥3 ports + 5V/3A supply · Qwiic cables · breadboard · phone hotspot (venue Wi-Fi sign-in pages won't work on the board)

## Schedule (~24 h)

| Phase | Hours | Done when |
|---|---|---|
| 0. Smoke tests | 0–2 | Board updated + on Wi-Fi; LED matrix demo; camera **and YubiKey** seen via hub; all 3 Modulinos detected; `ykman info` shows key model; start the liboqs build (slow) |
| 1. Data + keys | 2–8 | `get_features` returns real values over Bridge; camera frames; YubiKey enrol + `hmac-secret` → KEK on the UNO Q; ML-DSA sign/verify; encrypted key store round-trip |
| 2. Analyse | 8–14 | Baseline enrolment; the model returning a valid score; fail closed to duress if it doesn't |
| 3. Respond | 14–20 | Normal vs duress tokens + demo verifier, LED matrix states, webhook alert, dashboard (view-only) + audit log |
| 4. Polish | 20–24 | Grip enclosure, wiring diagram, README, rehearse calm vs coerced demo, backup video |

Team of 4: (1) MCU + sensors (2) camera + Edge Impulse model (3) YubiKey + post-quantum crypto (4) enclosure, demo, pitch.

## Things to verify in hour 0–2 (not yet tested on hardware)

- [ ] YubiKey shows up on the UNO Q's Linux side, and python-fido2 can open it (`/dev/hidraw*` permissions; App Lab's container may block USB — if so, run the auth service as a normal Python service on the board's Debian)
- [ ] Our YubiKey supports FIDO2 `hmac-secret` (fallback: HMAC-SHA1 challenge-response, YubiKey 5 only, 160-bit output — weaker)
- [ ] liboqs + liboqs-python build on the board (ARM64); ML-DSA-65 available in that version
- [ ] Modulino Qwiic port on UNO Q: does `Modulino.begin()` find the chain, or does it need `Wire1`?
- [ ] `ModulinoMovement::getX/getY/getZ` and `update()` names
- [ ] `ModulinoButtons` API: `update()` + `isPressed(i)`, or press callbacks?
- [ ] `Bridge.provide` returning a `String` arrives in Python as a `str`
- [ ] App Lab Python can `pip install` our requirements
- [ ] Camera index on the hub (`cv2.VideoCapture(0)`)
- [ ] The generic Edge Impulse `.eim` → `main.py import-model <user>`

## Limitations and risks

**Keys and "quantum-proof"**
- Say **post-quantum**, not "quantum-proof": we use NIST's post-quantum standards, but nothing is proven unbreakable.
- The YubiKey's own private key **can't** be copied to the UNO Q — that's by design. What the UNO Q stores is its own post-quantum keys, locked by a secret only the YubiKey can produce.
- Not post-quantum: the YubiKey's FIDO2 credential (ECDSA P-256) and the encrypted channel the board and YubiKey use for the `hmac-secret` exchange (ECDH P-256). This only happens over local USB, so an attacker would need physical access during login — say so in the threat model.
- The UNO Q has no secure element. Encrypted key files are safe if copied, but root access to a running board during login could read keys from RAM. Python also can't guarantee secrets are wiped from memory.
- Button PINs from 3 buttons are short, so the stored PIN hashes are guessable by someone who copies the key store. That's acceptable because the PIN alone unlocks nothing without the YubiKey.
- liboqs describes itself as for research and prototyping, not production.

**Hardware**
- One USB-C port: the hub now carries camera + YubiKey + power; weak power → random resets mid-demo.
- 3.3V logic: power analog sensors from 3.3V so outputs stay in ADC range.
- Soil moisture probe ≠ GSR sensor; use deltas only. Thermo humidity near the palm is likely the better sweat signal.
- Skin temperature changes over minutes — weak in an 8 s window; better as a "live hand present" check.
- 2 GB RAM: keep on-board vision light (Haar face count); liboqs + OpenCV + web server must fit together.

**On-device model (Edge Impulse)**
- It needs the generic model installed per person (personalised on the device by their baseline). Until one exists the system falls back to the dashboard's body score, then fails closed to the decoy.
- Runs once per approval, on the board, so latency and rate limits are not a concern; a missing or faulty model fails closed.
- Thresholds, not a single yes/no, and the model can't approve without the click and the YubiKey.

**Core problem**
- Stress ≠ duress (late, cold, coffee). False positives → soft responses only (step-up / silent alert), never hard lockout.
- The explicit duress PIN is the most reliable signal (as in real alarm panels and banks); sensors + AI back it up when the victim can't safely enter it.
- A calm, informed attacker beats physiological checks. Say so in the threat model.

**Privacy and ethics**
- Nothing is sent to a cloud model: frames are never stored and never leave the board; only consenting teammates on camera.
- Emotion recognition is legally sensitive (EU AI Act restricts it at work) → frame as "context risk scoring".
