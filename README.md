# YuDuino

**Hardware approval you can't fake, even under threat.** Built at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC.

Everything runs on an **Arduino UNO Q**. Every approval is a sealed envelope with three independent proofs: a **YubiKey** signature (who touched it), a tag from the board's **STM32 microcontroller** (the PIN was pressed on the real buttons for exactly the text on the LED matrix), and an **ML-DSA-65** post-quantum signature over everything. A handheld grip (shake, palm humidity and temperature, grip, sweat) and a USB camera feed Gemini, which judges **whether the person is acting freely**. Under duress the screen shows a normal "OK" and the envelope looks identical, but the STM32's tag secretly says "duress", which only the verifier can read, so it can raise a silent alarm. Details: **[crypto design](docs/CRYPTO.md)**.

**Test it:** [docs/TESTING.md](docs/TESTING.md) (laptop tests first, then the board).

## The vision: a language the attacker can never read

YuDuino is a small device that sits between a person and anything dangerous they can approve: moving money, deploying to production, letting an AI agent act. Nothing happens until a named person physically approves on it, and every approval is a **cryptographic signature, never an "OK" message**.

Hardware keys already prove *who* is approving. None of them help when someone in the room **forces** you to approve. YuDuino does.

While you approve, your body is "speaking" a physical language: tremor, sweat, touch and PIN rhythm, voice, your face and the scene around you. **Each reading means nothing on its own**: a shaky hand might just be coffee. Only when the readings are **aggregated** do they form a signal, and **Gemini is the translator** that turns them into one verdict: *under duress or not*.

The attacker is standing right there and can see everything, but can't read the language. If the translation says duress, YuDuino hands over a **decoy approval** that looks identical to a real one, moves nothing, freezes the funds and silently alerts the team.

**Why now:** on 29 October 2026, about US$6.34 billion was stolen from Binance hot wallets after attackers drove the signing service directly, with no human ever asked to approve ([details in the overview](docs/YuDuino-Overview.md#2-why-it-matters-the-binance-heist-29-october-2026)).

## How an approval works

1. **Request:** a laptop, server or AI agent asks for an action, with a one-time nonce and a 2-minute expiry.
2. **Show:** the UNO Q scrolls exactly what will be signed on its own LED matrix. The laptop screen is never trusted.
3. **Hold and enter PIN:** the user rests a hand on the mouse (palm on the grip pad) and enters their PIN on the Modulino Buttons (short and long presses). The PIN goes to the STM32 only; Linux never sees it. The sensors record every reading meanwhile.
4. **Tap:** the YubiKey signs a hash of exactly what was shown.
5. **Translate:** each reading is compared with the user's own baseline, and Gemini aggregates them all, plus one camera frame, into a verdict with reasons.
6. **Respond:** the STM32 turns the verdict into a tag that says real approval, second approver, or decoy, and only the verifier can read it. The verifier trusts signatures and tags, never an "OK".

**Safeguards:** Gemini fails closed (no reply, a late reply or a malformed reply means the decoy), it's reached over pinned HTTPS, PINs are never sent, and the PIN plus YubiKey touch are always required.

## The tracks we're targeting, and how YuDuino hits each one

| Track | Priority | How YuDuino hits it |
|---|---|---|
| **RS / Arduino:** build an intelligent system that can sense, analyse and respond to the real world | **Main** | **Sense:** grip sensors, camera and mic. **Analyse:** readings against the user's baseline, aggregated by Gemini. **Decide:** real, second approver or decoy. **Act:** LED matrix, signature release, silent alert and frozen funds. Uses all the mandatory hardware (UNO Q, camera, USB hub). Pitched as "smart safety monitoring", with accessibility via spoken readback. |
| **Tagged: Information Hidden in Plain Sight** (invent a physical language that encodes digital information) | Optional | **The whole system is the language.** The body's involuntary signals encode one bit, "under duress", that no single reading reveals. Gemini translates it. The attacker sees everything and can't read it, and the response looks the same either way. |
| **MLH Best Use of Gemini API** | Target | Gemini **does the duress calculation**: it aggregates every feature plus a camera frame into structured JSON. It also detects a second person in the scene, explains the transaction in plain English, and writes the incident reports. |
| **MLH Best Use of Tiger Data** | Target | **One record per usage** (feature scores, verdict, decision, label) in a hypertable. **Per-user and time-of-day baselines** as continuous aggregates, built from enrolment, every usage, a population prior and a within-session check. **False-alarm labels** tune it over time. Feeds the live dashboard. |
| **MLH Best Use of Vultr** | Add-on | One Vultr server is the **guardian backend**: the signature verifier, the stored incident reports and an **admin dashboard**. Its **response engine** runs the security protocol: alert the on-call team (Telegram, SMS or email), escalate if nobody responds, freeze the funds and require a second approver. It can lock and alert but never approve. |
| **MLH Best Use of ElevenLabs** | Add-on | Reads the transaction aloud for accessibility, and generates calm and scared test voices for a reliable demo. (It doesn't detect fear; Gemini does the translating.) |
| **DEV Writing Challenge** | Add-on | Publish the build story after the weekend. |
| **Free 3D printer** | Build | A **computer-mouse shell** that hides the whole device (palm pads, an LED-matrix window, three finger keys), plus a dock for the YubiKey and a **camera mount**. See [docs/MOUSE-DESIGN.md](docs/MOUSE-DESIGN.md). |
| **MLH Best Use of Solana** | Stretch | A devnet wallet program: a valid YuDuino signature releases funds, a decoy freezes them on-chain. |
| **MLH Best Use of MongoDB Atlas** | Stretch | Document data: user and device profiles, policies (spend limits, allow-lists, second-approver rules), guardian contacts and incident reports. |

Full details: **[challenge plan](docs/CHALLENGES.md)**.

## Our focuses, in priority order

The tracks above set what we spend time on:

1. **The end-to-end approval loop (RS/Arduino).** Request, trusted display, PIN, YubiKey, verdict, real or decoy signature, verifier. Everything else depends on it working.
2. **The hidden language (Tagged + Gemini).** Every sensor feeds the aggregate; Gemini's translation is the heart of the demo. Calm and coerced approvals must give visibly different verdicts.
3. **Personal baselines (Tiger Data).** One record per usage, with continuous-aggregate baselines, so the translation is about *this* person *right now*.
4. **A real-world response (Vultr).** Alerts, frozen funds and incident reports, so judges see the system *act*.
5. **A device nobody looks at twice (3D printer).** The whole device hides inside a computer mouse; the YubiKey and camera sit in a dock.
6. **Polish and accessibility (ElevenLabs, DEV).** Spoken readback, demo voices, write-up.
7. **Stretch goals, only if time (post-quantum ML-DSA signature, Solana, MongoDB).**

**Ground rules:** keep the prototype simple; never trust the laptop; the device fails closed; every build wave ends with a working demo.

## Hardware

| Part | Role |
|---|---|
| **Arduino UNO Q** | The brain. **STM32 side** (the trusted core): buttons and PIN, sensors, the LED matrix, the tag that proves a person pressed the PIN for the displayed text. **Linux side:** YubiKey, the ML-DSA key, camera, mic, Gemini call |
| **UNO Q LED matrix** | The trusted display, seen through a small frosted window in the mouse |
| **Arduino USB-C hub, power adaptor, USB-C cable** | The **dock** outside the mouse: power, camera and YubiKey on the UNO Q's single USB-C port, through the mouse's thin cable |
| **Arduino USB camera with mic** | Face, scene and voice |
| **YubiKey 5 NFC** | Proves who is approving |
| **Modulino Buttons** | PIN, approve and reject, PIN rhythm |
| **Modulino Movement** | Hand tremor |
| **Modulino Thermo** | Palm temperature and humidity (sweat) |
| **DFRobot touch sensor (D2)** | Is the grip actually held? |
| **DFRobot moisture sensor (A1)** | Second sweat and contact signal |
| **32 GB microSD + Icy Box** | Offline backup of the audit log |

Wiring and step-by-step bring-up: **[hardware plan](docs/HARDWARE-PLAN.md)**.

## Documentation

- **[Overview](docs/YuDuino-Overview.md):** the full product write-up: pitch, Binance case, approval flow, key release, post-quantum plan, traceability, limitations.
- **[Challenge plan](docs/CHALLENGES.md):** how we target each DurHack track.
- **[Development plan](docs/DEV-PLAN.md):** build waves, each advancing hardware, cryptography and extensions together, with a demo at the end of every wave.
- **[Hardware plan](docs/HARDWARE-PLAN.md):** wiring, pins and the bring-up order.
- **[Mouse design](docs/MOUSE-DESIGN.md):** the device hidden inside a computer mouse: layout, sensor map, display, 3D-printed shell, and the security trade-offs.
- **[Crypto design (YuSeal)](docs/CRYPTO.md):** keys, the three proofs, the hidden duress status, login, audit log, threat coverage, weak spots.
- **[Build flow](docs/BUILD-FLOW.md):** for each piece of hardware, what to code where, the test for each step, and the demo script.
- **[Design brief](docs/DESIGN-BRIEF.md):** the requirements the crypto was designed against, and why version 1 was replaced.
- **[Original plan](docs/PLAN.md):** early scaffold notes, downloads and things to verify on the hardware.

## Code layout

```
app/
  sketch/sketch.ino     STM32: reads sensors, exposes get_features / clear_pin over Bridge
    yuseal_mcu.h        (in sketch/) the STM32 trusted core: PIN, status, tag. Tested on a laptop
  python/
    main.py             entry point: `enrol <user>` and `approve <user> '<request>'`
    approve.py          the Linux side of one approval and of enrolment
    yuseal.py           the envelope, display rules, verifier checks, key store, audit log
    guardian.py         the verifier service (FastAPI): nonce, enrol, approve
    test_yuseal.py      41 tests, including the real C++ core
    yubikey_auth.py     YubiKey over USB (CTAP2); `RealYubiKey` for YuSeal
    camera.py           USB camera + Haar face count (frames kept in memory only)
    fusion_gemini.py    Gemini: frame + sensor summary → structured risk JSON
    pq_keystore.py, verifier.py, responder.py, risk_rules.py
                        the first scaffold (separate duress key). Superseded by YuSeal; kept for reference
tools/
  provision.py          makes the STM32's secrets (run once on a laptop)
  mcu_host_test.cpp     lets the tests drive the real STM32 code on a laptop
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
4. Make the STM32's secrets (PINs use `A B C` for a short press, `a b c` for a long press; make the duress PIN differ by one press's length), then flash the sketch from App Lab:
   ```bash
   python3 tools/provision.py --pin ABCABCAB --duress-pin ABCABCAb
   ```
5. Install the Python packages on the board: `pip install -r app/python/requirements.txt`
6. Let your user talk to the YubiKey over USB (`/dev/hidraw*`): add a udev rule for Yubico devices, or run as root while testing.
7. `cp .env.example .env` and fill in `GEMINI_API_KEY`, `GEMINI_MODEL`, `ALERT_WEBHOOK_URL`, `GUARDIAN_URL`, `ADDRESS_BOOK`. **Never commit `.env`.**
8. Start the guardian (laptop for Wave 1, Vultr later), then enrol once and approve:
   ```bash
   cd app/python && uvicorn guardian:app --port 8000
   ```
   ```bash
   python3 app/python/main.py enrol jonah
   ```
   ```bash
   python3 app/python/main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"}'
   ```

Step by step with a test for each: **[build flow](docs/BUILD-FLOW.md)**. `secrets.h`, `tools/out/` and `device.json` are created locally and are gitignored.

## Status

**The crypto and the STM32 core are tested on a laptop (41 tests); the board glue is not yet run on the UNO Q.** The unverified calls (Bridge arguments, LED matrix, Buttons, YubiKey over USB) are listed with fallbacks in [docs/BUILD-FLOW.md](docs/BUILD-FLOW.md#5-things-we-couldnt-check-without-the-board-and-what-to-do-if-they-fail) and marked `VERIFY` in the code. Build order: [Wave 1 of the development plan](docs/DEV-PLAN.md#wave-1-skeleton-minimal-end-to-end-prototype).
