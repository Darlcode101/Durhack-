# YuDuino: challenge plan

*How YuDuino targets each DurHack challenge. Written 14 November 2026. Every design choice should serve at least one of the target challenges below.*

> **The vision that ties every track together:** YuDuino is a **language the attacker can never read**. Each reading (tremor, sweat, touch rhythm, voice, face, scene) means nothing on its own. Aggregated, the readings form a signal, and **the on-device model translates** it into one verdict: under duress or not.

Back to the **[overview](YuDuino-Overview.md)** · **[hardware plan](HARDWARE-PLAN.md)** · **[development plan](DEV-PLAN.md)**

## At a glance

| Track | Priority | YuDuino's angle |
|---|---|---|
| **Overall theme: Composition** (art, music, tech, idea mixing) | **Main** | Many meaningless signals composed into one; a mouse + YubiKey + AI. See [COMPOSITION.md](COMPOSITION.md) |
| **Marshall Wace: New Worlds** | **Main** | A new world of data (the hand at the moment of authority) and an invisible authenticator. See [INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md) |
| RS / Arduino: sense, analyse and respond to the real world | **Main** | Duress-aware approval device: sensors and camera in, a real, escalated or decoy approval out |
| DEV Writing Challenge | Add-on (free) | Write-up after the weekend |
| MLH Best Use of ElevenLabs | Add-on (cheap) | Reads the transaction aloud; generates test voices for the demo |
| MLH Best Use of Solana | Stretch | Devnet wallet program: a valid signature releases funds, a decoy freezes them |
| MLH Best Use of MongoDB Atlas | Stretch (if time) | Document data: profiles and incident reports |
| Entire | Skip | It rewards our AI coding workflow, not the product |

## 0. The overall theme and the main audience

**Overall theme: Composition** ("explore art, music and tech; idea mixing; new combinations"). Judged on **Creativity & Innovation, Technical Competence & Execution, Research & Learning, Polish & Completion**. How YuDuino answers it: **[COMPOSITION.md](COMPOSITION.md)**.

**Main audience: Marshall Wace**, whose challenge is **"New Worlds"** (open a door to the unexplored: new data, ideas or something novel; judged on creativity, technical complexity and good presentation). Our pitch, in Jonah's words, with a defensible "new" claim: **[INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md)**. What exists already: **[PRIOR-ART.md](PRIOR-ART.md)**.

## 1. RS / Arduino (main challenge)

The brief asks for an intelligent system that captures data, analyses sensor inputs, makes a decision and triggers an action. The UNO Q, a camera and USB hubs are mandatory. YuDuino follows those four steps exactly:

| Step | What YuDuino does | Parts |
|---|---|---|
| **Sense** | During an 8-second capture window while the grip is held: tremor, palm humidity and temperature, moisture, click and movement style, one camera frame, audio | Modulino Movement, Thermo; the mouse's own switches (read-only tap); DFRobot touch and moisture; USB camera with mic |
| **Analyse** | Each reading becomes a feature against the user's own baseline; the on-device Edge Impulse model aggregates them and calculates the duress verdict | UNO Q (STM32 side for sensors, Linux side for camera, audio, the model) |
| **Decide** | Low risk: real approval. Uncertain: a step-up result for the customer's system to handle. Duress: decoy approval. An unknown hand: a quiet, ordinary-looking failure | UNO Q |
| **Act** | In mouse mode there is no screen; releases the signature (never an "OK"), returns a `duress` verdict (alerts are the customer's to send) and quietly fails an unknown hand | LED matrix, YubiKey, verifier |

All three mandatory parts are used: **UNO Q** (the brain), **camera** (face count, expression, voice), **USB-C hub** (power, camera, YubiKey).

**Pitch it as** the brief's "smart safety monitoring" example. Reading the transaction aloud (see ElevenLabs) also covers its "accessibility" example.

**Demo tip:** show a live graph of the sensor readings next to the device, so judges can watch the sensing and the decision happen in real time.

## 2. The on-device model (Edge Impulse)

Not a prize track: this is how the duress and owner judgement is made. Details: **[EDGE-IMPULSE.md](EDGE-IMPULSE.md)**.

- **An Edge Impulse model on the UNO Q does the duress calculation.** The readings from the moment of the transaction become one feature vector, and the model returns the probability of duress. It is the translator of the hidden language.
- **Generic model, personalised on the device.** Trained in Studio on synthetic data only; each mouse scores against the user's own per-hour baseline, which never leaves the device.
- **No cloud call.** Nothing is sent anywhere, so there is nothing to block, spoof or impersonate.
- **Safeguards:**
  - **Fail closed:** no model, a model fault or a malformed output means the decoy key.
  - **The final decision and the keys stay on the STM32.** The model's score is an input; the STM32 decides and tags.

## 3. MLH Best Use of MongoDB Atlas (stretch, if time)

**Benched for now; we only build this if there's time left.** The core plan works without it: the core plan stores nothing in it.

If we build it, MongoDB Atlas holds the **document-shaped** data, so it never overlaps with the local time-series store:

| Collection | What each document holds |
|---|---|
| `users` and `devices` | User and device profiles, YubiKey public key and attestation, enrolment config (chosen backup gesture, enrolment date) |
| `incidents` | One document per decoy approval or alert: the transaction, the risk scores, the model's score, who was alerted, and how it was resolved (real duress or false alarm) |

**How the two split:** the local store on the board answers "how does this reading compare to normal over time?"; MongoDB would answer "who is this, and what happened in this incident?".

## 4. Conflict with "all processing onboard"

The design rule is that raw data stays on the UNO Q. The Edge Impulse model runs on the board, so nothing about it goes to the cloud. MongoDB Atlas, if added, is a cloud service, so:

- **MongoDB Atlas** (if added) only receives derived scores, labels, settings and incident reports, written **after** the decision. The cloud is never in the approval path. 
- **Later version:** padded, fixed-interval messages to resist traffic side channels.

## 5. 3D printer (free)

In priority order:

1. **Mouse shell** that hides the whole device: the UNO Q with a frosted window over the LED matrix, three finger keys over the Modulino Buttons, and palm pads over the touch, moisture and Thermo sensors. Layout and trade-offs: [MOUSE-DESIGN.md](MOUSE-DESIGN.md).
2. **Dock** for the USB-C hub, camera and YubiKey.
3. **Camera mount** at face height.

## 6. Other MLH prizes

- **DEV Writing Challenge: yes.** Publish the build story after the weekend. It costs no hack time and pays $100.
- **ElevenLabs: yes, cheap.** It reads the transaction aloud for accessibility, and generates calm and scared test voices so the duress demo is reliable (lower priority). **ElevenLabs does not detect fear.** Fear detection stays with the onboard pitch, shake and speaking-rate features.
- **Solana: stretch goal.** A devnet program acts as the wallet: it only releases funds when given a valid YuDuino signature over the exact transaction. A decoy signature freezes the funds and raises the alarm on-chain instead. This ties directly to the Binance story.
- **Skip Entire**: it rewards our AI coding workflow, not the product.
