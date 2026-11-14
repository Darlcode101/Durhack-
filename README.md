# YuDuino

**Hardware approval you can't fake, even under threat.** Built at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC.

## The vision: a language the attacker can never read

YuDuino is a small device that sits between a person and anything dangerous they can approve: moving money, deploying to production, letting an AI agent act. Nothing happens until a named person physically approves on it, and every approval is a **cryptographic signature, never an "OK" message**.

Hardware keys already prove *who* is approving. None of them help when someone in the room **forces** you to approve. YuDuino does.

While you approve, your body is "speaking" a physical language: tremor, sweat, touch and PIN rhythm, voice, your face and the scene around you. **Each reading means nothing on its own**: a shaky hand might just be coffee. Only when the readings are **aggregated** do they form a signal, and **Gemini is the translator** that turns them into one verdict: *under duress or not*.

The attacker is standing right there and can see everything, but can't read the language. If the translation says duress, YuDuino hands over a **decoy approval** that looks identical to a real one, moves nothing, freezes the funds and silently alerts the team.

**Why now:** on 29 October 2026, about US$6.34 billion was stolen from Binance hot wallets after attackers drove the signing service directly, with no human ever asked to approve ([details in the overview](docs/YuDuino-Overview.md#2-why-it-matters-the-binance-heist-29-october-2026)).

## How an approval works

1. **Request:** a laptop, server or AI agent asks for an action, with a one-time nonce and a 2-minute expiry.
2. **Show:** the UNO Q scrolls exactly what will be signed on its own LED matrix. The laptop screen is never trusted.
3. **Hold and enter PIN:** the user holds the sensor grip and enters their PIN on the Modulino Buttons. An 8-second window captures every reading.
4. **Tap:** the YubiKey signs a hash of exactly what was shown.
5. **Translate:** each reading is compared with the user's own baseline, and Gemini aggregates them all, plus one camera frame, into a verdict with reasons.
6. **Respond:** real approval, second approver, or decoy. The microcontroller chooses which key signs; the verifier only trusts signatures.

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
| **Free 3D printer** | Build | A handheld **sensor grip** with palm pads, a **UNO Q enclosure** with an LED-matrix window and a YubiKey dock, a **privacy hood** over the PIN buttons, and a **camera mount**. |
| **MLH Best Use of Solana** | Stretch | A devnet wallet program: a valid YuDuino signature releases funds, a decoy freezes them on-chain. |
| **MLH Best Use of MongoDB Atlas** | Stretch | Document data: user and device profiles, policies (spend limits, allow-lists, second-approver rules), guardian contacts and incident reports. |

Full details: **[challenge plan](docs/CHALLENGES.md)**.

## Our focuses, in priority order

The tracks above set what we spend time on:

1. **The end-to-end approval loop (RS/Arduino).** Request, trusted display, PIN, YubiKey, verdict, real or decoy signature, verifier. Everything else depends on it working.
2. **The hidden language (Tagged + Gemini).** Every sensor feeds the aggregate; Gemini's translation is the heart of the demo. Calm and coerced approvals must give visibly different verdicts.
3. **Personal baselines (Tiger Data).** One record per usage, with continuous-aggregate baselines, so the translation is about *this* person *right now*.
4. **A real-world response (Vultr).** Alerts, frozen funds and incident reports, so judges see the system *act*.
5. **A device that looks like a product (3D printer).** Grip, enclosure, YubiKey dock.
6. **Polish and accessibility (ElevenLabs, DEV).** Spoken readback, demo voices, write-up.
7. **Stretch goals, only if time (post-quantum ML-DSA signature, Solana, MongoDB).**

**Ground rules:** keep the prototype simple; never trust the laptop; the device fails closed; every build wave ends with a working demo.

## Hardware

| Part | Role |
|---|---|
| **Arduino UNO Q** | The brain. Linux side: camera, mic, features, Gemini call. STM32 microcontroller side: real-time sensors and the signing keys |
| **UNO Q LED matrix** | The trusted display |
| **Arduino USB-C hub, power adaptor, USB-C cable** | Power, camera and YubiKey on the UNO Q's single USB-C port |
| **Arduino USB camera with mic** | Face, scene and voice |
| **YubiKey 5 NFC** | Proves who is approving |
| **Modulino Buttons** | PIN, approve and reject, PIN rhythm |
| **Modulino Movement** | Hand tremor |
| **Modulino Thermo** | Palm temperature and humidity (sweat) |
| **DFRobot touch sensor (D2)** | Is the grip actually held? |
| **DFRobot moisture sensor (A0)** | Second sweat and contact signal |
| **32 GB microSD + Icy Box** | Offline backup of the audit log |

Wiring and step-by-step bring-up: **[hardware plan](docs/HARDWARE-PLAN.md)**.

## Documentation

- **[Overview](docs/YuDuino-Overview.md):** the full product write-up: pitch, Binance case, approval flow, key release, post-quantum plan, traceability, limitations.
- **[Challenge plan](docs/CHALLENGES.md):** how we target each DurHack track.
- **[Development plan](docs/DEV-PLAN.md):** build waves, each advancing hardware, cryptography and extensions together, with a demo at the end of every wave.
- **[Hardware plan](docs/HARDWARE-PLAN.md):** wiring, pins and the bring-up order.
- **[Original plan](docs/PLAN.md):** early scaffold notes, downloads and things to verify on the hardware.

## Code layout

```
app/
  sketch/sketch.ino     STM32: reads sensors, exposes get_features / clear_pin over Bridge
  python/
    main.py             Linux entry point: capture window → translate → respond
    camera.py           USB camera + face count (frames kept in memory only)
    risk_rules.py       scaffold rules engine (to be replaced: Gemini alone decides, see the dev plan)
    fusion_gemini.py    Gemini: frame + features → structured duress JSON
    responder.py        grant / step-up / decoy + silent alert + audit log
    auth_webauthn.py    YubiKey via WebAuthn (stub)
docs/
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

Scaffold only: **not yet run on the UNO Q.** Several library calls are marked `VERIFY` in the code; the checklist is in [docs/PLAN.md](docs/PLAN.md#things-to-verify-in-hour-02-code-assumes-these-not-yet-tested-on-hardware). Build order: [Wave 1 of the development plan](docs/DEV-PLAN.md#wave-1-skeleton-minimal-end-to-end-prototype).
