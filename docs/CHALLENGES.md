# YuDuino: challenge plan

*How YuDuino targets each DurHack challenge. Written 14 November 2026. Every design choice should serve at least one of the target challenges below.*

> **The vision that ties every track together:** YuDuino is a **language the attacker can never read**. Each reading (tremor, sweat, touch rhythm, voice, face, scene) means nothing on its own. Aggregated, the readings form a signal, and **Gemini translates** it into one verdict: under duress or not.

Back to the **[overview](YuDuino-Overview.md)** · **[hardware plan](HARDWARE-PLAN.md)**

## At a glance

| Track | Priority | YuDuino's angle |
|---|---|---|
| RS / Arduino: sense, analyse and respond to the real world | **Main** | Duress-aware approval device: sensors and camera in, a real, escalated or decoy approval out |
| Tagged: Information Hidden in Plain Sight | Optional | The readings are a language: meaningless alone, a signal when aggregated; Gemini translates; the attacker can't read it |
| MLH Best Use of Gemini API | Target | Multimodal duress judge and plain-English transaction explainer |
| MLH Best Use of Tiger Data | Target | One record per usage; baselines as continuous aggregates; false-alarm labels; audit log |
| DEV Writing Challenge | Add-on (free) | Write-up after the weekend |
| MLH Best Use of ElevenLabs | Add-on (cheap) | Reads the transaction aloud; generates test voices for the demo |
| MLH Best Use of Vultr | Add-on | The guardian backend: incident reports and admin dashboard, verifier, and a response engine that alerts the team and locks funds |
| MLH Best Use of Solana | Stretch | Devnet wallet program: a valid signature releases funds, a decoy freezes them |
| MLH Best Use of MongoDB Atlas | Stretch (if time) | Document data: profiles, policies, guardian contacts and incident reports |
| Entire | Skip | It rewards our AI coding workflow, not the product |

## 1. RS / Arduino (main challenge)

The brief asks for an intelligent system that captures data, analyses sensor inputs, makes a decision and triggers an action. The UNO Q, a camera and USB hubs are mandatory. YuDuino follows those four steps exactly:

| Step | What YuDuino does | Parts |
|---|---|---|
| **Sense** | During an 8-second capture window while the grip is held: tremor, palm humidity and temperature, moisture, PIN rhythm, one camera frame, audio | Modulino Movement, Thermo, Buttons; DFRobot touch and moisture; USB camera with mic |
| **Analyse** | Each reading becomes a feature against the user's own baseline; Gemini aggregates them and calculates the duress verdict | UNO Q (STM32 side for sensors, Linux side for camera, audio, Gemini) |
| **Decide** | Low risk: real approval. Medium: ask for a second approver. Duress or duress PIN: decoy approval | UNO Q |
| **Act** | Shows the transaction and result on the LED matrix, releases the signature (never an "OK"), sends a silent alert under duress | LED matrix, YubiKey, verifier |

All three mandatory parts are used: **UNO Q** (the brain), **camera** (face count, expression, voice), **USB-C hub** (power, camera, YubiKey).

**Pitch it as** the brief's "smart safety monitoring" example. Reading the transaction aloud (see ElevenLabs) also covers its "accessibility" example.

**Demo tip:** show a live graph of the sensor readings next to the device, so judges can watch the sensing and the decision happen in real time.

## 2. Tagged: Information Hidden in Plain Sight (optional)

The brief: invent a physical language that encodes digital information.

**The whole system is the language.** Under duress, the body involuntarily "speaks" a physical language: a shaking hand, sweaty palms, a tense voice, a hesitant PIN rhythm, a grip held differently, a second face in the frame. Each sensor records one part of that language and turns it into data:

| Physical "word" | Recorded by | What it encodes |
|---|---|---|
| Tremor | Modulino Movement | Shaking hands |
| Sweat | Modulino Thermo (humidity), DFRobot moisture | Sweaty palms |
| Touch and PIN rhythm | DFRobot touch, Modulino Buttons | Hesitant or rushed input |
| Voice | Camera mic | Fear or stress in the voice |
| Face | Camera | Expression, and whether someone else is present |

**No single word means anything; the sentence does.** A shaking hand could be coffee, damp palms could be a warm room, a fast PIN could be a busy day. On its own, each reading is noise. Aggregated, they become a signal.

**Gemini is the translator.** It reads all of these signals together, compared with the user's own baseline, and translates them into one digital bit: *under duress or not*.

**Hidden in plain sight, on purpose.** The attacker is standing right there and can see everything, but can't read it. The user doesn't have to do anything visible, and the device's response looks the same either way: a decoy approval is indistinguishable from a real one on the LED matrix. Only the verifier learns the translation.

**Optional deliberate "word".** A user can also choose a secret grip tilt or tap rhythm at enrolment that means "I'm being forced", for when the involuntary signals aren't strong enough. It's a backup, not the main pitch.

## 3. MLH Best Use of Gemini API

- **Gemini does the duress calculation.** The UNO Q turns each reading into a feature against the user's baseline. Gemini receives all of them together, plus one camera frame and the decoded transaction, aggregates them and returns the verdict and its reasons as **structured JSON**. It is the translator of the hidden language.
- **Scene and second-person detection.** From the frame: is someone else there, is the user looking at someone off-camera, does the scene look normal?
- **Plain-English transaction explainer.** Gemini explains what the transaction actually does (for example, "this delegation lets X keep draining the wallet") for the display and for any second approver.
- **Incident reports.** For every decoy or alert, Gemini writes the report admins see on the Vultr dashboard.
- **Fear in the voice.** Gemini can judge vocal stress from a short audio clip. Onboard features (pitch, shake and speaking rate) are the fallback, and the default if we keep audio on the device.
- **Safeguards:**
  - **Fail closed:** no reply, a late reply or a malformed reply means the decoy key.
  - **Pinned HTTPS to Google**, so nobody can impersonate Gemini and send "all clear".
  - **Minimal onboard veto:** only extreme readings or an unplugged sensor force the decoy. It's a safety net, not a second calculation.
  - **The final decision and the keys stay on the STM32.** Gemini can't approve on its own: the PIN and the YubiKey touch are always required, and PINs are never sent.

## 4. MLH Best Use of Tiger Data

Tiger Data is PostgreSQL with time-series extensions. **It stores one record per usage**: every approval session, with its sensor feature scores, Gemini's verdict, the decision and (later) a label. Never raw audio or video.

**Why Tiger Data fits:** duress detection is all about "is this reading unusual *for this person, right now*?". That is a time-series question, and Tiger Data answers it in plain SQL:

- **Hypertable of usages:** one row per approval session, partitioned by time, with a relational `users` table alongside in the same database.
- **Baselines as continuous aggregates:** per-user and per-time-of-day baselines (for example, your usual tremor at 9 am versus 11 pm) are pre-computed and kept up to date automatically, so the device gets its baseline in one fast query.
- **Where a baseline comes from:**
  1. A **one-minute enrolment** at setup, recorded calm.
  2. **Every usage** after that.
  3. A **population prior** for brand-new users, which shifts toward the user's own baseline as their usages accumulate.
  4. A **within-session check**: readings when the grip is picked up versus at confirmation, so a sudden change mid-approval stands out even without history.
- **False-alarm labels:** when a duress flag turns out to be wrong, the usage is labelled, and thresholds are tuned from those labels (this is how YuDuino "learns from false alarms").
- **Audit log:** the hash-chained approval log, mirrored from the microSD.
- **Live dashboard:** real-time charts from the continuous aggregates, which also serve as the RS demo graph. Compression keeps months of usages on the free tier.

## 5. MLH Best Use of MongoDB Atlas (stretch, if time)

**Benched for now; we only build this if there's time left.** The core plan works without it: until then, policies and guardian contacts live in a config file on the device and the guardian backend, and incident reports are stored on the Vultr guardian backend.

If we build it, MongoDB Atlas holds the **document-shaped** data, so it never overlaps with Tiger Data's time-series:

| Collection | What each document holds |
|---|---|
| `users` and `devices` | User and device profiles, YubiKey public key and attestation, enrolment config (chosen backup gesture, enrolment date) |
| `policies` | Spend limits, destination allow-lists, quiet hours, and second-approver rules (who, and above what amount) |
| `guardians` | Emergency contacts and how to reach them for silent alerts |
| `incidents` | One document per decoy approval or alert: the transaction, the risk scores, Gemini's explanation, who was alerted, and how it was resolved (real duress or false alarm) |

**How the two databases split:** Tiger Data answers "how does this reading compare to normal over time?"; MongoDB answers "who is this, what are they allowed to do, and what happened in this incident?". The Vultr guardian backend reads both. When an incident is resolved as a false alarm, the label is also written back to the matching usage in Tiger Data.

## 6. Conflict with "all processing onboard"

The design rule is that raw data stays on the UNO Q. Gemini and Tiger Data are cloud services, so:

- **Gemini** only ever receives the aggregated features and one frame (plus an audio clip only if we decide the voice signal needs it). Never PINs. It fails closed over pinned HTTPS, so a failed or spoofed call can never cause a real approval.
- **Tiger Data** (and MongoDB Atlas, if added) only receive derived scores, labels, settings and incident reports, written **after** the decision. The cloud is never in the approval path. (The device keeps a local copy of its policies so it works offline.)
- **Later version:** a local model (such as Gemma) on the UNO Q's Linux side, and padded, fixed-interval messages to resist traffic side channels.

## 7. 3D printer (free)

In priority order:

1. **Handheld grip** holding Modulino Movement, Thermo and the touch sensor, with palm pads over the Thermo and moisture sensors so readings are consistent.
2. **UNO Q enclosure** with a window for the LED matrix and a YubiKey dock that only exposes the touch pad.
3. **Privacy hood** over the Modulino Buttons PIN pad.
4. **Camera mount** at face height.

## 8. Other MLH prizes

- **DEV Writing Challenge: yes.** Publish the build story after the weekend. It costs no hack time and pays $100.
- **ElevenLabs: yes, cheap.** It reads the transaction aloud for accessibility, and generates calm and scared test voices so the duress demo is reliable (lower priority). **ElevenLabs does not detect fear.** Fear detection stays with Gemini audio or the onboard pitch, shake and speaking-rate features.
- **Vultr: yes.** Few teams will enter it, so it's worth the small effort. One Vultr server is the **guardian backend**: it **hosts and stores the incident reports** (one report per decoy approval or alert, with the transaction, risk scores and Gemini's explanation) on the server or in Vultr Object Storage, and serves an **admin dashboard** where admins review them and mark each one as real duress or a false alarm. It also runs the signature verifier and the silent-alert service, and reads per-usage scores and baselines from Tiger Data (false-alarm labels are written back there). No GPU training.
  - **Response engine (runs the security protocol).** When a decoy approval or alert fires, the server carries out the protocol automatically:
    1. **Alert the on-call team** by SMS, Telegram or email, with the incident report link.
    2. **Escalate** to the next person (and then the guardian contacts) if nobody acknowledges within a set time.
    3. **Freeze or hold** the affected funds or account through the wallet API (or the Solana devnet program in the stretch goal).
    4. **Require a second approver** for that user's next actions until an admin closes the incident.
  - **It can only make things safer.** The server can lock, hold and alert, but it can never approve or release anything; only a fresh YuDuino signature can.
  - **Fails safe.** If the Vultr server is down, the device still issues the decoy and the verifier still refuses it, and alerts queue up on the device and are sent when the server is reachable again.
- **Solana: stretch goal.** A devnet program acts as the wallet: it only releases funds when given a valid YuDuino signature over the exact transaction. A decoy signature freezes the funds and raises the alarm on-chain instead. This ties directly to the Binance story.
- **Skip Entire**: it rewards our AI coding workflow, not the product.
