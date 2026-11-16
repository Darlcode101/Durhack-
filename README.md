# YuDuino

**Hardware approval you can't fake, even under threat.** Built at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC.

**Peace of mind in a new world.** The past few months were the worst ever for cyber security (the Binance attack, where an attacker used a compromised laptop and an internal AI tool to make Binance's own signer approve theft of about US$6.3 billion). YuDuino is a **future-proof, post-quantum-signed** approval system that **new users can use without understanding it, because there are no inputs**: it is hidden inside a computer mouse that works exactly like a normal mouse. No screen, no PIN, nothing extra to do: the user just clicks, and the authentication happens in the background. To our knowledge it is a **new combination** of known parts that we couldn't find put together before ([prior art](docs/PRIOR-ART.md)). It also learns the owner's hand all day and **quietly rejects anyone else**. See [the design](#the-design-a-mouse-you-just-use) below.

Everything runs on an **Arduino UNO Q**. Every approval is a sealed envelope with three independent proofs: a **YubiKey** signature (possession, no touch), a tag from the board's **STM32 microcontroller** (a real click with a palm on the grip happened just before, over a hash of the sensor summary the owner check is run on), and an **ML-DSA-65** post-quantum signature over everything. A handheld grip (shake, palm humidity and temperature, grip, sweat) and a USB camera feed an **Edge Impulse model running on the board**, which judges **whether the person is acting freely**. A generic model (trained in Edge Studio on synthetic data only) is personalised on the device against the user's own per-hour baseline, which never leaves the device. Under duress the requester just sees a normal "accepted" and the envelope looks identical, but the STM32's tag secretly says "duress", which only the customer's verifier can read, so the customer's system can raise a silent alarm. Details: **[crypto design](docs/CRYPTO.md)**.

**Test it:** [docs/TESTING.md](docs/TESTING.md) (laptop tests first, then the board).

## Result

YuDuino came **2nd in the RS / Arduino track at DurHack 2026**. The deck we presented is in **[presentation/YuDuino-DurHack-2026-pitch.pdf](presentation/YuDuino-DurHack-2026-pitch.pdf)**, with the YubiKey + UNO Q diagram used on the slides ([PNG](presentation/yubikey-unoq.png), [SVG](presentation/yubikey-unoq.svg)).

## The design: a mouse you just use

The whole device lives **inside a normal-working office mouse**. The user does **nothing extra**: no PIN, no gesture, no screen. They click "Process transaction" like any button, the STM32 sees that **real physical click**, and the check runs silently from sensor data.

- **Hidden.** Nothing about it looks like an authenticator. [docs/MOUSE-DESIGN.md](docs/MOUSE-DESIGN.md)
- **It learns you all day.** A mouse is held for hours, so it builds a rich, per-hour baseline of your grip, tremor, sweat and temperature on the device, which fixes the "not enough data to know what's irregular" problem. This is learning only: nothing is judged or flagged from everyday use, and duress is checked **only at the moment of a transaction**. [docs/BASELINE.md](docs/BASELINE.md)
- **It knows whose hand it is.** The verifier compares aggregated click, movement, grip and body features with the **YubiKey's registered user** and **quietly rejects anyone else**. An impostor sees only ordinary failures, can retry forever, and never passes. [docs/OWNER-CHECK.md](docs/OWNER-CHECK.md)
- **The approval is invisible.** A physical click is the trigger and everything else is background. [docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md)

**Misdirection.** The mouse is so unusual that even the system logs and the transaction breakdown would make an attacker assume a remote key or another ledger. That is misdirection on top of the crypto, not instead of it ([docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md#misdirection-what-an-attacker-sees-in-the-logs)).

**Be clear about the trade-off.** This gives up the **trusted display** and the **PIN**. Without a screen, malware on the laptop could show one transaction and send another, and there is no deliberate "I'm being forced" signal; duress is detected purely passively. The owner check is statistical and will sometimes turn away the real owner. Details and the full list of weak spots are in [STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md#what-we-lose-read-this).

**What the code does today.** The repo implements this zero-input mouse mode: the STM32 core (click, arm, tag, attested sensor summary), the reference verifier's owner check with its quiet rejection, and the Linux flow, all tested on a laptop. The earlier PIN-and-LED-matrix "strong mode" has been removed from the code (it is in git history at commit `2c455f8`). The board glue (click tap, sensors, Bridge, YubiKey without a touch) has not been run on the UNO Q yet.

## YuSeal: every security measure you could want going into 2027

- **ML-DSA post-quantum seal** (NIST FIPS 204)
- **Keys never leave the hardware**
- **STM32 click attestation** (a real finger made the click)
- **AES-256-GCM** at rest
- **Private, chip-derived unlock salt**
- **Tamper-evident audit chain**

The best encryption still doesn't stop someone standing at your desk. That is what the mouse is for.

**Why now:** 2026 is one of the worst years for security on record. On 29 October 2026, about US$6.34 billion was stolen from Binance hot wallets after attackers drove the signing service directly, with no human ever asked to approve ([details in the overview](docs/YuDuino-Overview.md#2-why-it-matters-the-binance-heist-29-october-2026)).

## How an approval works

Nobody does anything but click. Full flow and the trade-offs: [docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md).

1. **Request:** a laptop, server or AI agent asks for an action, with a one-time nonce and a 2-minute expiry.
2. **Click:** the person clicks "Process transaction" like any button. The STM32 sees that real click, and whether a palm was on the grip, through a read-only tap on the mouse's switch line.
3. **Arm:** within 1.5 seconds of that click the Linux side arms the STM32 with the approval's digest. The STM32 refuses without a fresh click (one click arms once, with a rate limit), then releases the salt that lets the YubiKey (no touch) unlock the post-quantum key.
4. **Translate:** each reading is compared with the user's own baseline, and the Edge Impulse model on the board aggregates them (with a face count from the camera; no frame leaves the device) into a verdict.
5. **Seal:** the STM32 turns the verdict into a tag over the status (real, step-up or decoy), the request digest, the click age and a hash of the sensor summary. Only the verifier can read it.
6. **Check:** the customer's verifier (the reference library in `yuseal.py`) verifies all three proofs, then runs the **owner check** on the attested sensor summary. Another person gets a plain "unavailable", the same as any other failure, and can retry forever without passing.

**Safeguards:** the model runs on the board, so there is no cloud call to block or impersonate. It fails closed (no model, a model fault or a malformed output means the decoy), and the click, the YubiKey and the STM32's tag are always required.

## Key design decisions

1. **Keeping it local.** We started with Gemini and Tiger Data, then moved to storing user data on the device and using classical ML rather than a cloud LLM. Nothing leaves the device.
2. **Edge cases.** Coworkers and passers-by don't count (the over-the-shoulder rule), and readings only register while your hand is on the mouse.
3. **K-means anomaly detection.** Trained on 2000 calm rows; 17 input columns go into a K-means anomaly block. The inputs measure how far you are from your own mean, so the model is personalised without retraining: z = (x − μ) / σ against your mean for that time of day.
4. **Someone just back from a run.** After 5+ minutes away from the mouse, if sweat or shake is high but falling, that's recovery from exercise. The body score is capped below the duress threshold, so that alone can't signal duress.

Details: [docs/EDGE-IMPULSE.md](docs/EDGE-IMPULSE.md).

## Track

Entered in **RS / Arduino** (sense, analyse and respond to the real world) and placed **2nd**. **Sense:** grip, movement, sweat and click, all day, only while a hand is on the mouse. **Analyse:** at a transaction, the last minute against your baseline, scored by the on-device K-means model. **Decide and act:** a real approval, a decoy under duress, or a quiet rejection of someone else's hand. See [docs/CHALLENGES.md](docs/CHALLENGES.md).

## Hardware

| Part | Role |
|---|---|
| **Arduino UNO Q** | The brain. **STM32 side** (the trusted core): the click tap, sensors, the tag that proves a real click and what the sensors read. **Linux side:** YubiKey, the ML-DSA key, camera, mic, the Edge Impulse model |
| **Arduino USB-C hub, power adaptor, USB-C cable** | The **dock** outside the mouse: power, camera and YubiKey on the UNO Q's single USB-C port, through the mouse's thin cable |
| **Arduino USB camera with mic** | Face, scene and voice |
| **YubiKey 5 NFC** | Proves who is approving |
| **Modulino Buttons** | Bench stand-in for the click when there is no donor mouse yet. In the mouse, a read-only tap on the donor mouse's own switch is the click |
| **Modulino Movement** | Hand tremor |
| **Modulino Thermo** | Palm temperature and humidity (sweat) |
| **DFRobot touch sensor (D2)** | Is the grip actually held? |
| **DFRobot moisture sensor (A1)** | Second sweat and contact signal |
| **32 GB microSD + Icy Box** | Offline backup of the audit log |

Wiring and step-by-step bring-up: **[hardware plan](docs/HARDWARE-PLAN.md)**.

## Documentation

- **[Pitch deck](presentation/YuDuino-DurHack-2026-pitch.pdf):** the slides we presented at DurHack 2026.

- **[Overview](docs/YuDuino-Overview.md):** the full write-up, matching the pitch deck: pitch, Binance case, how it works, key design decisions, limits.
- **[Challenges and result](docs/CHALLENGES.md):** the track we entered and how it went.
- **[Development plan](docs/DEV-PLAN.md):** build waves, each advancing hardware, cryptography and extensions together, with a demo at the end of every wave.
- **[Hardware plan](docs/HARDWARE-PLAN.md):** wiring, pins and the bring-up order.
- **[Edge Impulse model](docs/EDGE-IMPULSE.md):** the generic model trained on synthetic data, personalised on the device by the user's own baseline, the encrypted profile, and the training steps.
- **[All-day baseline](docs/BASELINE.md):** how the mouse learns each person's normal all day, the privacy limits, filtering out mouse movement, and time-of-day drift.
- **[Prior art](docs/PRIOR-ART.md):** what already exists (mouse dynamics, biometric and sensor mice, duress detection, decoy wallets, post-quantum keys), what is genuinely different, and what we must not claim.
- **[Composition](docs/COMPOSITION.md):** the DurHack theme and how YuDuino answers it.
- **[Marshall Wace: New Worlds](docs/INSTITUTIONAL-FIT.md):** our pitch for their challenge, with an honest check of each claim.
- **[Invisible approval](docs/STEALTH-APPROVAL.md):** no screen, no PIN, no extra input: the flow, what we lose and how we cover it.
- **[Owner check](docs/OWNER-CHECK.md):** how the mouse tells the registered user from anyone else, and what happens on a false reject.
- **[Mouse design](docs/MOUSE-DESIGN.md):** the device hidden inside a computer mouse: layout, sensor map, 3D-printed shell, and the security trade-offs.
- **[Test cases](docs/TEST-CASES.md):** the YuSeal crypto test cases and their results, on the laptop and on the board.
- **[Crypto design (YuSeal)](docs/CRYPTO.md):** keys, the three proofs, the hidden duress status, login, audit log, threat coverage, weak spots.
- **[Build flow](docs/BUILD-FLOW.md):** for each piece of hardware, what to code where, the test for each step, and the demo script.
- **[Design brief](docs/DESIGN-BRIEF.md):** the requirements the crypto was designed against, and why version 1 was replaced.
- **[Mouse proposal](docs/MOUSE.md):** putting the sensors inside an ordinary mouse, for all-day baselines and a device nobody notices.
- **[Original plan](docs/PLAN.md):** early scaffold notes, downloads and things to verify on the hardware.

## Code layout

```
app/
  sketch/sketch.ino     STM32: click tap and sensors; Bridge calls arm_approval / get_unlock_salt / get_attest / seal_approval / get_features
    baseline_mcu.h      (in sketch/) the STM32's per-hour rolling baseline (mean and spread per sensor per hour)
    yuseal_mcu.h        (in sketch/) the STM32 trusted core: click, arm, status, tag. Tested on a laptop
    sketch.yaml         library versions App Lab builds with (Modulino 0.10.0 for the newer Thermo)
  bringup/              one small sketch per hardware step (click, Qwiic, DFRobot, core)
  dashboard/
    server.py           live duress monitor (FastAPI): camera + YuNet faces, sensors, YubiKey, Edge Impulse model, verdict
    index.html          the dashboard page: live view, local history, incident log
    store.py            the local store (SQLite on the board): readings, approvals, incidents, baselines
    applab_relay.py     runs inside the App Lab app: copies STM32 readings to a file the dashboard reads
    restart.sh          (re)starts the dashboard on the board and fetches the face model
    install_autostart.sh, yuduino-dashboard.service
                        start the sensor app and dashboard at boot; restart the dashboard if it crashes
  python/
    main.py             entry point: `enrol`, `approve`, `learn`, `seed`, `import-model`
    userprofile.py      the encrypted per-user profile (AES-256-GCM, key derived by the STM32): baseline copy, training rows, model
    learner.py          learns while the mouse is used: one feature row a minute, raw samples discarded; keeps the last minute in RAM for the transaction check
    bridge.py           the Linux side's link to the STM32 calls
    approve.py          the Linux side of one approval and of enrolment
    yuseal.py           the envelope, request rules, verifier checks and owner check, key store, audit log
    verify_cli.py       a tiny reference verifier for trying it: `enrol`, `nonce`, `check`
    test_yuseal.py      75 tests, including the real C++ core
    yubikey_auth.py     YubiKey over USB (CTAP2); `RealYubiKey` for YuSeal
    camera.py           USB camera + Haar face count (frames kept in memory only)
    edge_model.py       the on-device Edge Impulse model: sensor window → duress score
    pq_keystore.py, verifier.py, responder.py, risk_rules.py
                        the first scaffold (separate duress key). Superseded by YuSeal; kept for reference
presentation/            the DurHack 2026 pitch deck (PDF) and the slide diagram
tools/
  provision.py          makes the STM32's secrets (run once on a laptop)
  gen_generic_training.py  makes the synthetic training set for the generic Edge Impulse model
  mcu_host_test.cpp     lets the tests drive the real STM32 code on a laptop
  yk_probe.py           run on the board: which YubiKey mode works without a touch
  setup_yk_hmac.py      fallback: program the YubiKey's HMAC-SHA1 slot without touch
docs/
```

## Setup (on the UNO Q)

1. Install **Arduino App Lab** on your laptop, update the UNO Q and connect it to Wi-Fi (use a phone hotspot at the venue).
2. In App Lab, create a new app, copy `app/sketch/` into it and install the `Arduino_Modulino` library. Run it so the MCU serves sensor data.
3. On your laptop, check the code first (no liboqs build needed any more; `cryptography>=48` has ML-DSA built in):
   ```bash
   pip install -r app/python/requirements.txt fastapi httpx
   ```
   ```bash
   cd app/python && python3 -m unittest test_yuseal -v
   ```
4. Make the STM32's secret (no PIN to choose), then flash the sketch from App Lab:
   ```bash
   python3 tools/provision.py
   ```
5. Install the Python packages on the board: `pip install -r app/python/requirements.txt`
6. Let your user talk to the YubiKey over USB (`/dev/hidraw*`): add a udev rule for Yubico devices, or run as root while testing.
7. `cp .env.example .env` and fill in `PROFILE_DIR` and `EI_ANOMALY_LIMIT`, then `python3 main.py import-model <user> generic.eim` (see [Edge Impulse](docs/EDGE-IMPULSE.md)). **Never commit `.env`.**
8. Seed the baseline (15 minutes with a hand on the mouse), or run `learn <user>` all day: `python3 app/python/main.py seed jonah 15`.
9. Enrol once, then approve. The customer's own system sends a request and a one-time nonce (`Verifier.new_nonce()` in `yuseal.py`) and checks the envelope that comes back (`Verifier.check()`); `verify_cli.py` does that from the command line:
   ```bash
   python3 app/python/main.py enrol jonah > package.json
   python3 app/python/verify_cli.py enrol jonah package.json
   ```
   ```bash
   N=$(python3 app/python/verify_cli.py nonce)
   python3 app/python/main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"}' --nonce "$N" > envelope.json
   ```

Step by step with a test for each: **[build flow](docs/BUILD-FLOW.md)**. `secrets.h`, `tools/out/` and `device.json` are created locally and are gitignored.

### Live dashboard (on the UNO Q)

Shows the duress verdict live, with the camera, every signal against your own normal, the model's score, and history from the local store.

1. Create an App Lab app, put `app/sketch/` in its `sketch/` folder and `app/dashboard/applab_relay.py` as its `python/main.py`, and start it. It writes the STM32's readings to `<app>/live/features.json` once every 200 ms.
2. History is stored automatically in a local file on the board (`STORE_PATH`, default `app/dashboard/data/yuduino.db`). Nothing leaves the device.
3. Start it and open `http://<board-ip>:8080`:
   ```bash
   ~/Durhack-/app/dashboard/restart.sh
   ```
4. Press **Re-learn normal** while using the device normally for 30 s; sweat and movement are judged against that.

Only derived numbers are stored, and only on the board (no frames, no PINs, no keys). Camera frames stay in memory and never leave the board; neither do the model's inputs.

## Status

**The crypto, the STM32 core, the owner check and the Linux flow are tested on a laptop (75 tests).** On the UNO Q (14–15 November, with the earlier strong-mode sketch):

| Verified on the board | Notes |
|---|---|
| YuSeal tests | `test_yuseal` passed on the board (38 tests at the time), with `cryptography` 50's ML-DSA |
| Bridge | `get_features` returns its JSON string to Python |
| Modulino Thermo, Movement, Buttons | On **`Wire1`**. Needs **Arduino_Modulino 0.10.0**: newer Thermos use a GXHT30C at 0x45, which 0.7.0 can't find |
| YubiKey 5 over the hub | FIDO2.1 with `hmac-secret`, firmware 5.7.4; readable without sudo via a udev rule |
| Camera | Frames at 640×480. YuNet (dashboard) finds turned and background faces that Haar misses |
| Live dashboard | Ran on the board as a service (camera, sensors, YubiKey, verdict, history), before the move to Edge Impulse and the local store |

**Not yet verified on the board:** the Edge Impulse model and the encrypted profile, the STM32's per-hour baseline and its persistence, the mouse-mode sketch (click tap, `arm_approval` / `get_attest` and other Bridge calls), the YubiKey without a touch over USB, `RealYubiKey` signing, `enrol` / `approve` end to end, and the touch and moisture sensors (no power yet: the shared 3V3 join). The board needs the **USB-C hub's own cable** in its port (not the PD input) to act as USB host for the YubiKey and camera. The unverified calls are listed with fallbacks in [docs/BUILD-FLOW.md](docs/BUILD-FLOW.md#5-things-we-couldnt-check-without-the-board-and-what-to-do-if-they-fail) and marked `VERIFY` in the code. Test steps: [docs/TESTING.md](docs/TESTING.md). Build order: [Wave 1 of the development plan](docs/DEV-PLAN.md#wave-1-skeleton-minimal-end-to-end-prototype).
