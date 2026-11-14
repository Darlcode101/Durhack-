# YuDuino: challenge plan

*How YuDuino targets each DurHack challenge. Written 14 November 2026. Every design choice should serve at least one of the four target challenges below.*

Back to the **[overview](YuDuino-Overview.md)** · **[hardware plan](HARDWARE-PLAN.md)**

## At a glance

| Track | Priority | YuDuino's angle |
|---|---|---|
| RS / Arduino: sense, analyse and respond to the real world | **Main** | Duress-aware approval device: sensors and camera in, a real, escalated or decoy approval out |
| Tagged: Information Hidden in Plain Sight | Optional | A covert duress language in the grip, plus a decoy marker hidden in the LED approval animation |
| MLH Best Use of Gemini API | Target | Multimodal duress judge and plain-English transaction explainer |
| MLH Best Use of Tiger Data | Target | Time-series of capture windows, per-user baselines, false-alarm labels and the audit log |
| DEV Writing Challenge | Add-on (free) | Write-up after the weekend |
| MLH Best Use of ElevenLabs | Add-on (cheap) | Reads the transaction aloud; generates test voices for the demo |
| MLH Best Use of Vultr | Add-on (cheap) | Hosts the verifier and dashboard |
| MLH Best Use of Solana | Stretch | Devnet program that only moves funds with a valid YuDuino signature |
| MongoDB Atlas, Entire | Skip | MongoDB overlaps with Tiger Data; Entire is about our workflow, not the product |

## 1. RS / Arduino (main challenge)

The brief asks for an intelligent system that captures data, analyses sensor inputs, makes a decision and triggers an action. The UNO Q, a camera and USB hubs are mandatory. YuDuino follows those four steps exactly:

| Step | What YuDuino does | Parts |
|---|---|---|
| **Sense** | During an 8-second capture window while the grip is held: tremor, palm humidity and temperature, moisture, PIN rhythm, one camera frame, audio | Modulino Movement, Thermo, Buttons; DFRobot touch and moisture; USB camera with mic |
| **Analyse** | Rules engine compares readings with the user's own resting baseline; Gemini gives a second opinion | UNO Q (STM32 side for sensors, Linux side for camera, audio, Gemini) |
| **Decide** | Low risk: real approval. Medium: ask for a second approver. Duress or duress PIN: decoy approval | UNO Q |
| **Act** | Shows the transaction and result on the LED matrix, releases the signature (never an "OK"), sends a silent alert under duress | LED matrix, YubiKey, verifier |

All three mandatory parts are used: **UNO Q** (the brain), **camera** (face count, expression, voice), **USB-C hub** (power, camera, YubiKey).

**Pitch it as** the brief's "smart safety monitoring" example. Reading the transaction aloud (see ElevenLabs) also covers its "accessibility" example.

**Demo tip:** show a live graph of the sensor readings next to the device, so judges can watch the sensing and the decision happen in real time.

## 2. Tagged: Information Hidden in Plain Sight (optional)

The brief: invent a physical language that encodes digital information.

- **Covert duress language (main idea).** A secret tilt of the grip or a tap rhythm on the buttons means "I'm being forced". Modulino Movement and Buttons read it. To an attacker watching, it looks like a normal approval, so the duress bit is hidden in plain sight. Each user picks their own gesture at enrolment, so it works like a duress PIN that nobody can see being typed.
- **Decoy marker in the approval animation (second piece).** The LED matrix plays an approval animation that looks the same for real and decoy approvals. A small pattern in it encodes the result and a fragment of the approval hash, which only the verifier's camera can decode.

## 3. MLH Best Use of Gemini API

- **Multimodal duress judge.** Gemini receives one camera frame, a summary of the sensor scores and the decoded transaction. It returns a risk score and its reasons as **structured JSON**.
- **Plain-English transaction explainer.** Gemini explains what the transaction actually does (for example, "this delegation lets X keep draining the wallet") for the display and for any second approver.
- **Fear in the voice.** Gemini can judge vocal stress from a short audio clip. Onboard features (pitch, shake and speaking rate) are the fallback, and the default if we keep audio on the device.
- **Rules.** AI can only make things safer: a "danger" verdict can switch to the decoy, but an "all clear" never approves on its own. PINs and raw audio are never sent unless we choose to send a clip. If Gemini is slow or offline, the rules engine decides alone.

## 4. MLH Best Use of Tiger Data

Tiger Data is PostgreSQL with time-series extensions:

- **Hypertable of capture windows:** one row per sensor reading per approval attempt (derived scores, not raw camera or audio).
- **Per-user baselines as continuous aggregates:** each user's resting tremor, humidity and PIN rhythm, kept up to date automatically.
- **False-alarm labels:** when a duress flag turns out to be wrong, it is labelled so thresholds can be tuned (this is how YuDuino "learns from false alarms").
- **Audit log:** the hash-chained approval log, mirrored from the microSD.
- **Live dashboard:** real-time charts from the continuous aggregates, which also serves as the RS demo graph. Compression keeps months of readings on the free tier.

## 5. Conflict with "all processing onboard"

The design rule is that raw data stays on the UNO Q. Gemini and Tiger Data are cloud services, so:

- **Gemini** only ever receives one frame and the scores (plus an audio clip only if we decide the voice signal needs it). Never PINs. It can only raise the risk, so a failed or manipulated call can never cause an approval.
- **Tiger Data** only receives derived scores and labels, written **after** the decision. The cloud is never in the approval path.
- **Later version:** a local model (such as Gemma) on the UNO Q's Linux side, and padded, fixed-interval messages to resist traffic side channels.

## 6. 3D printer (free)

In priority order:

1. **Handheld grip** holding Modulino Movement, Thermo and the touch sensor, with palm pads over the Thermo and moisture sensors so readings are consistent.
2. **UNO Q enclosure** with a window for the LED matrix and a YubiKey dock that only exposes the touch pad.
3. **Privacy hood** over the Modulino Buttons PIN pad.
4. **Camera mount** at face height.

## 7. Other MLH prizes

- **DEV Writing Challenge: yes.** Publish the build story after the weekend. It costs no hack time and pays $100.
- **ElevenLabs: yes, cheap.** It reads the transaction aloud for accessibility, and generates calm and scared test voices so the duress demo is reliable (lower priority). **ElevenLabs does not detect fear.** Fear detection stays with Gemini audio or the onboard pitch, shake and speaking-rate features.
- **Vultr: yes, cheap.** Host the verifier and the dashboard on a Vultr instance using the free credits.
- **Solana: stretch, but on-pitch.** A devnet program acts as the verifier: it only moves funds when given a valid YuDuino signature over the exact transaction. Decoy approvals never move funds. This ties directly to the Binance story.
- **Skip MongoDB Atlas** (it overlaps with Tiger Data) **and Entire** (it rewards our AI coding workflow, not the product).
