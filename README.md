# YuDuino

**Hardware approval you can't fake, even under threat.** Built at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC.

**Peace of mind in an AI-accelerated world.** The past few months were the worst ever for cyber security (the Binance attack, where an attacker used a compromised laptop and an internal AI tool to make Binance's own signer approve theft of about US$6.3 billion). YuDuino is a **future-proof, post-quantum-signed** approval system that **new users can use without understanding it, because there are no inputs**: it is hidden inside a computer mouse that works exactly like a normal mouse. No screen, no PIN, nothing extra to do: the user just clicks, and the authentication happens in the background. To our knowledge it is a **new combination** of known parts that we couldn't find put together before ([prior art](docs/PRIOR-ART.md)). It also learns the owner's hand all day and **quietly rejects anyone else**. See [the target design](#the-target-design-a-mouse-you-just-use) below.

Everything runs on an **Arduino UNO Q**. Every approval is a sealed envelope with three independent proofs: a **YubiKey** signature (possession, no touch), a tag from the board's **STM32 microcontroller** (a real click with a palm on the grip happened just before, over a hash of the sensor summary the owner check is run on), and an **ML-DSA-65** post-quantum signature over everything. A handheld grip (shake, palm humidity and temperature, grip, sweat) and a USB camera feed Gemini, which judges **whether the person is acting freely**. Under duress the requester just sees a normal "accepted" and the envelope looks identical, but the STM32's tag secretly says "duress", which only the guardian can read, so it can raise a silent alarm. Details: **[crypto design](docs/CRYPTO.md)**.

**Test it:** [docs/TESTING.md](docs/TESTING.md) (laptop tests first, then the board).

## Who it's for

The main audience is **Marshall Wace** (the hedge fund), whose challenge is **"New Worlds"**. The pitch, in our own words and with an honest claim about novelty, is in **[docs/INSTITUTIONAL-FIT.md](docs/INSTITUTIONAL-FIT.md)**; what already exists is in **[docs/PRIOR-ART.md](docs/PRIOR-ART.md)**. The overall DurHack theme is **Composition** ([docs/COMPOSITION.md](docs/COMPOSITION.md)).

## The target design: a mouse you just use

Design change (2026-11-14): the whole device now lives **inside a normal-working mouse**. The user does **nothing extra**: no PIN, no gesture, no screen. They click "Process transaction" like any button, the STM32 sees that **real physical click**, and the check runs silently from sensor data.

- **Hidden.** Nothing about it looks like an authenticator. [docs/MOUSE-DESIGN.md](docs/MOUSE-DESIGN.md)
- **It learns you all day.** A mouse is held for hours, so it builds a rich, per-hour baseline of your grip, tremor, sweat and temperature in Tiger Data, which fixes the "not enough data to know what's irregular" problem. [docs/BASELINE.md](docs/BASELINE.md)
- **It knows whose hand it is.** The guardian compares aggregated click, movement, grip and body features with the **YubiKey's registered user** and **quietly rejects anyone else**. An impostor sees only ordinary failures, can retry forever, and never passes. [docs/OWNER-CHECK.md](docs/OWNER-CHECK.md)
- **The approval is invisible.** A physical click is the trigger and everything else is background. [docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md)

**Misdirection.** The mouse is so unusual that even the system logs and the transaction breakdown would make an attacker assume a remote key or another ledger. That is misdirection on top of the crypto, not instead of it ([docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md#misdirection-what-an-attacker-sees-in-the-logs)).

**Be clear about the trade-off.** This gives up the **trusted display** and the **PIN**. Without a screen, malware on the laptop could show one transaction and send another, and there is no deliberate "I'm being forced" signal; duress is detected purely passively. The guardian's limits, step-up, Gemini's check of the request and a cancel window are what cover that. The owner check is statistical and will sometimes turn away the real owner (handled by a second approver). Details and the full list of weak spots are in [STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md#what-we-lose-read-this).

**What the code does today.** The repo implements this zero-input mouse mode: the STM32 core (click, arm, tag, attested sensor summary), the guardian's owner check with its quiet rejection, and the Linux flow, all tested on a laptop. The earlier PIN-and-LED-matrix "strong mode" has been removed from the code (it is in git history at commit `2c455f8`). The board glue (click tap, sensors, Bridge, YubiKey without a touch) has not been run on the UNO Q yet.

## The vision: a language the attacker can never read

YuDuino is a small device that sits between a person and anything dangerous they can approve: moving money, deploying to production, letting an AI agent act. Nothing happens until a named person physically approves on it, and every approval is a **cryptographic signature, never an "OK" message**.

Hardware keys already prove *who* is approving. None of them help when someone in the room **forces** you to approve. YuDuino does.

While you approve, your body is "speaking" a physical language: tremor, sweat, touch and click timing, voice, your face and the scene around you. **Each reading means nothing on its own**: a shaky hand might just be coffee. Only when the readings are **aggregated** do they form a signal, and **Gemini is the translator** that turns them into one verdict: *under duress or not*.

The attacker is standing right there and can see everything, but can't read the language. If the translation says duress, YuDuino hands over a **decoy approval** that looks identical to a real one, moves nothing, freezes the funds and silently alerts the team.

**Why now:** on 29 October 2026, about US$6.34 billion was stolen from Binance hot wallets after attackers drove the signing service directly, with no human ever asked to approve ([details in the overview](docs/YuDuino-Overview.md#2-why-it-matters-the-binance-heist-29-october-2026)).

## How an approval works

Nobody does anything but click. Full flow and the trade-offs: [docs/STEALTH-APPROVAL.md](docs/STEALTH-APPROVAL.md).

1. **Request:** a laptop, server or AI agent asks for an action, with a one-time nonce and a 2-minute expiry.
2. **Click:** the person clicks "Process transaction" like any button. The STM32 sees that real click, and whether a palm was on the grip, through a read-only tap on the mouse's switch line.
3. **Arm:** within 1.5 seconds of that click the Linux side arms the STM32 with the approval's digest. The STM32 refuses without a fresh click (one click arms once, with a rate limit), then releases the salt that lets the YubiKey (no touch) unlock the post-quantum key.
4. **Translate:** each reading is compared with the user's own baseline, and Gemini aggregates them, plus one camera frame, into a verdict with reasons.
5. **Seal:** the STM32 turns the verdict into a tag over the status (real, second approver or decoy), the request digest, the click age and a hash of the sensor summary. Only the guardian can read it.
6. **Check:** the guardian verifies all three proofs, then runs the **owner check** on the attested sensor summary. Another person gets a plain "unavailable", the same as any other failure, and can retry forever without passing.

**Safeguards:** Gemini fails closed (no reply, a late reply or a malformed reply means the decoy), it's reached over pinned HTTPS, and the click, the YubiKey and the STM32's tag are always required.

## The tracks we're targeting, and how YuDuino hits each one

| Track | Priority | How YuDuino hits it |
|---|---|---|
| **RS / Arduino:** build an intelligent system that can sense, analyse and respond to the real world | **Main** | **Sense:** the mouse's grip, click, movement and body sensors, all day, plus the camera and mic. **Analyse:** readings against the user's baseline, aggregated by Gemini. **Decide:** real, second approver or decoy. **Act:** signature release, a quiet rejection of other hands, silent alert and frozen funds. Uses all the mandatory hardware (UNO Q, camera, USB hub). Pitched as "smart safety monitoring", with accessibility via spoken readback. |
| **Overall theme: Composition** (art, music, tech, idea mixing) | **Main** | Many meaningless signals composed into one; a mouse + YubiKey + AI; the hand's sensor stream as a score. [docs/COMPOSITION.md](docs/COMPOSITION.md) |
| **Marshall Wace: New Worlds** (open a door to new data, ideas or something novel) | **Main** | A new world of data, the human hand at the moment of authority, and an authenticator nobody can see. [docs/INSTITUTIONAL-FIT.md](docs/INSTITUTIONAL-FIT.md) |
| **QRT: Tagged: Information Hidden in Plain Sight** (invent a physical language that encodes digital information) | Optional | **The whole system is the language.** The body's involuntary signals encode one bit, "under duress", that no single reading reveals, and the whole shape of a hand at work says *who* is holding it. Gemini and the owner check translate them. Nobody knows the mouse measures any of it, so there is nothing to steal or copy, and the response looks like an ordinary result either way. |
| **MLH Best Use of Gemini API** | Target | Gemini **does the duress calculation**: it aggregates every feature plus a camera frame into structured JSON. It also detects a second person in the scene, explains the transaction in plain English, and writes the incident reports. |
| **MLH Best Use of Tiger Data** | Target | **Rolling time-series from the mouse:** one row of aggregate features a minute, all day, in a **hypertable**. **Continuous aggregates** give per-user baselines by hour of day, **`time_bucket` queries** give the z-score at approval time, and **compression and retention** keep raw rows for days and aggregates for months. Approvals and false-alarm labels sit alongside. Feeds the live dashboard. See [docs/CHALLENGES.md](docs/CHALLENGES.md#4-mlh-best-use-of-tiger-data). |
| **MLH Best Use of Vultr** | Add-on | One Vultr server is the **guardian backend**: the signature verifier, the stored incident reports and an **admin dashboard**. Its **response engine** runs the security protocol: alert the on-call team (Telegram, SMS or email), escalate if nobody responds, freeze the funds and require a second approver. It can lock and alert but never approve. |
| **MLH Best Use of ElevenLabs** | Add-on | Reads the transaction aloud for accessibility, and generates calm and scared test voices for a reliable demo. (It doesn't detect fear; Gemini does the translating.) |
| **DEV Writing Challenge** | Add-on | Publish the build story after the weekend. |
| **Free 3D printer** | Build | A base plate, standoffs and inserts for a **donor mouse** (or a prototype shell) that hide the whole device, plus a dock for the YubiKey and a **camera mount**. See [docs/MOUSE-DESIGN.md](docs/MOUSE-DESIGN.md). |
| **MLH Best Use of Solana** | Stretch | A devnet wallet program: a valid YuDuino signature releases funds, a decoy freezes them on-chain. |
| **MLH Best Use of MongoDB Atlas** | Stretch | Document data: user and device profiles, policies (spend limits, allow-lists, second-approver rules), guardian contacts and incident reports. |

Full details: **[challenge plan](docs/CHALLENGES.md)**.

## Our focuses, in priority order

The tracks above set what we spend time on:

1. **The end-to-end approval loop (RS/Arduino).** Request, the physical click, background checks, verdict, real or decoy signature, verifier. Everything else depends on it working.
2. **The hidden language (Tagged + Gemini).** Every sensor feeds the aggregate; Gemini's translation is the heart of the demo. Calm and coerced approvals must give visibly different verdicts.
3. **Personal baselines (Tiger Data).** A rolling stream from the mouse, rolled up by continuous aggregates into per-hour baselines, so the translation is about *this* person *right now*.
4. **A real-world response (Vultr).** Alerts, frozen funds and incident reports, so judges see the system *act*.
5. **A device nobody looks at twice, that learns you all day (3D printer).** The whole device hides inside a computer mouse. Because a mouse is held for hours, it also **passively collects a rich baseline** of your grip, tremor, sweat and temperature, which solves the "not enough data to know what's irregular" problem ([docs/BASELINE.md](docs/BASELINE.md)). The YubiKey and camera sit in a dock.
6. **Polish and accessibility (ElevenLabs, DEV).** Spoken readback, demo voices, write-up.
7. **Stretch goals, only if time (post-quantum ML-DSA signature, Solana, MongoDB).**

**Ground rules:** keep the prototype simple; never trust the laptop; the device fails closed; every build wave ends with a working demo.

## Hardware

| Part | Role |
|---|---|
| **Arduino UNO Q** | The brain. **STM32 side** (the trusted core): the click tap, sensors, the tag that proves a real click and what the sensors read. **Linux side:** YubiKey, the ML-DSA key, camera, mic, Gemini call |
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

- **[Overview](docs/YuDuino-Overview.md):** the full product write-up: pitch, Binance case, approval flow, key release, post-quantum plan, traceability, limitations.
- **[Challenge plan](docs/CHALLENGES.md):** how we target each DurHack track.
- **[Development plan](docs/DEV-PLAN.md):** build waves, each advancing hardware, cryptography and extensions together, with a demo at the end of every wave.
- **[Hardware plan](docs/HARDWARE-PLAN.md):** wiring, pins and the bring-up order.
- **[All-day baseline](docs/BASELINE.md):** how the mouse learns each person's normal all day, the privacy limits, filtering out mouse movement, and time-of-day drift.
- **[Prior art](docs/PRIOR-ART.md):** what already exists (mouse dynamics, biometric and sensor mice, duress detection, decoy wallets, post-quantum keys), what is genuinely different, and what we must not claim.
- **[Composition](docs/COMPOSITION.md):** the DurHack theme and how YuDuino answers it.
- **[Marshall Wace: New Worlds](docs/INSTITUTIONAL-FIT.md):** our pitch for their challenge, with an honest check of each claim.
- **[Invisible approval](docs/STEALTH-APPROVAL.md):** no screen, no PIN, no extra input: the flow, what we lose and how we cover it.
- **[Owner check](docs/OWNER-CHECK.md):** how the mouse tells the registered user from anyone else, and what happens on a false reject.
- **[Mouse design](docs/MOUSE-DESIGN.md):** the device hidden inside a computer mouse: layout, sensor map, 3D-printed shell, and the security trade-offs.
- **[Crypto design (YuSeal)](docs/CRYPTO.md):** keys, the three proofs, the hidden duress status, login, audit log, threat coverage, weak spots.
- **[Build flow](docs/BUILD-FLOW.md):** for each piece of hardware, what to code where, the test for each step, and the demo script.
- **[Design brief](docs/DESIGN-BRIEF.md):** the requirements the crypto was designed against, and why version 1 was replaced.
- **[Mouse proposal](docs/MOUSE.md):** putting the sensors inside an ordinary mouse, for all-day baselines and a device nobody notices.
- **[Original plan](docs/PLAN.md):** early scaffold notes, downloads and things to verify on the hardware.

## Code layout

```
app/
  sketch/sketch.ino     STM32: click tap and sensors; Bridge calls arm_approval / get_unlock_salt / get_attest / seal_approval / get_features
    yuseal_mcu.h        (in sketch/) the STM32 trusted core: click, arm, status, tag. Tested on a laptop
  python/
    main.py             entry point: `enrol <user>` and `approve <user> '<request>'`
    approve.py          the Linux side of one approval and of enrolment
    yuseal.py           the envelope, request rules, verifier checks and owner check, key store, audit log
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
4. Make the STM32's secret (no PIN to choose), then flash the sketch from App Lab:
   ```bash
   python3 tools/provision.py
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

**The crypto, the STM32 core, the owner check and the Linux flow are tested on a laptop (54 tests); the board glue is not yet run on the UNO Q.** The unverified calls (the click tap, Bridge arguments, the YubiKey without a touch over USB) are listed with fallbacks in [docs/BUILD-FLOW.md](docs/BUILD-FLOW.md#5-things-we-couldnt-check-without-the-board-and-what-to-do-if-they-fail) and marked `VERIFY` in the code. Test steps: [docs/TESTING.md](docs/TESTING.md). Build order: [Wave 1 of the development plan](docs/DEV-PLAN.md#wave-1-skeleton-minimal-end-to-end-prototype).
