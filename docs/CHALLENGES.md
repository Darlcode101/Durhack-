# YuDuino: challenge plan

*How YuDuino targets each DurHack challenge. Written 14 November 2026. Every design choice should serve at least one of the target challenges below.*

> **The vision that ties every track together:** YuDuino is a **language the attacker can never read**. Each reading (tremor, sweat, touch rhythm, voice, face, scene) means nothing on its own. Aggregated, the readings form a signal, and **Gemini translates** it into one verdict: under duress or not.

Back to the **[overview](YuDuino-Overview.md)** · **[hardware plan](HARDWARE-PLAN.md)** · **[development plan](DEV-PLAN.md)**

## At a glance

| Track | Priority | YuDuino's angle |
|---|---|---|
| **Overall theme: Composition** (art, music, tech, idea mixing) | **Main** | Many meaningless signals composed into one; a mouse + YubiKey + AI; the hand's signal rendered as music. See [COMPOSITION.md](COMPOSITION.md) |
| **Marshall Wace: New Worlds** | **Main** | A new world of data (the hand at the moment of authority) and an invisible authenticator. See [INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md) |
| RS / Arduino: sense, analyse and respond to the real world | **Main** | Duress-aware approval device: sensors and camera in, a real, escalated or decoy approval out |
| Tagged: Information Hidden in Plain Sight (QRT) | Optional | The readings are a language: meaningless alone, a signal when aggregated; Gemini translates; the attacker can't read it |
| MLH Best Use of Gemini API | Target | Multimodal duress judge and plain-English transaction explainer |
| MLH Best Use of Tiger Data | Target | The mouse's rolling per-minute stream in a hypertable; hourly continuous aggregates for per-user baselines; compression and retention; approvals and labels |
| SGX FX: protect assets in a trading market storm | Overlap (small) | "Tilt guard": market storm from their data × operator state from the mouse → step-up and early warning |
| Neptune North: actors that stay resilient when comms fail | Overlap (mention only) | Each mouse decides locally and fails closed offline; approvals from several people compose |
| Accenture: redesign a frustrating accepted process with AI | Optional framing | "Everyone accepts PINs and pop-ups as how security works": we remove them |
| DEV Writing Challenge | Add-on (free) | Write-up after the weekend |
| MLH Best Use of ElevenLabs | Add-on (cheap) | Reads the transaction aloud; generates test voices for the demo |
| MLH Best Use of Vultr | Add-on | The guardian backend: incident reports and admin dashboard, verifier, and a response engine that alerts the team and locks funds |
| MLH Best Use of Solana | Stretch | Devnet wallet program: a valid signature releases funds, a decoy freezes them |
| MLH Best Use of MongoDB Atlas | Stretch (if time) | Document data: profiles, policies, guardian contacts and incident reports |
| Entire | Skip | It rewards our AI coding workflow, not the product |

## 0. The overall theme and the main audience

**Overall theme: Composition** ("explore art, music and tech; idea mixing; new combinations"). Judged on **Creativity & Innovation, Technical Competence & Execution, Research & Learning, Polish & Completion**. YuDuino is a composition at every level (signals, proofs, an everyday object plus a YubiKey plus AI) and we suggest a **music angle**: the hand's sensor stream played as a score. Full framing, a judging-criteria map and the demo: **[COMPOSITION.md](COMPOSITION.md)**.

**Main audience: Marshall Wace**, whose challenge is **"New Worlds"**: open a door to the unexplored (new data, ideas or something novel). They judge creativity, technical complexity and good presentation. Our answer is three doors: **new data** (the human hand at the moment of authority), a **new idea** (authentication that is invisible) and **something novel** (a hand's signature as a language, even audible as music). Also the institutional fit: treasury and trader authorisation, insider and coercion risk, audit trails. Details, objections and a demo: **[INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md)**.

## 1. RS / Arduino (main challenge)

The brief asks for an intelligent system that captures data, analyses sensor inputs, makes a decision and triggers an action. The UNO Q, a camera and USB hubs are mandatory. YuDuino follows those four steps exactly:

| Step | What YuDuino does | Parts |
|---|---|---|
| **Sense** | During an 8-second capture window while the grip is held: tremor, palm humidity and temperature, moisture, click and movement style, one camera frame, audio | Modulino Movement, Thermo; the mouse's own switches (read-only tap); DFRobot touch and moisture; USB camera with mic |
| **Analyse** | Each reading becomes a feature against the user's own baseline; Gemini aggregates them and calculates the duress verdict | UNO Q (STM32 side for sensors, Linux side for camera, audio, Gemini) |
| **Decide** | Low risk: real approval. Medium: ask for a second approver. Duress: decoy approval. An unknown hand: a quiet, ordinary-looking failure | UNO Q |
| **Act** | In mouse mode there is no screen; releases the signature (never an "OK"), sends a silent alert under duress or on repeated unknown-hand tries | LED matrix, YubiKey, verifier |

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

**Optional deliberate "word" (dropped in mouse mode).** An earlier idea let the user choose a secret grip tilt or tap rhythm that means "I'm being forced". The mouse must work with no extra input, so this is **not** included; duress is detected only passively. It is a real loss, listed in [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#what-we-lose-read-this).

**The same language also says *who*.** The aggregated shape of a hand at work (click, movement, grip, body) identifies the registered user, so the mouse can quietly reject anyone else ([OWNER-CHECK.md](OWNER-CHECK.md)). Nobody knows those features are measured, so there is nothing to steal.

## 3. MLH Best Use of Gemini API

- **Gemini does the duress calculation.** The UNO Q turns each reading into a feature against the user's baseline. Gemini receives all of them together, plus one camera frame and the decoded transaction, aggregates them and returns the verdict and its reasons as **structured JSON**. It is the translator of the hidden language.
- **Scene and second-person detection.** From the frame: is someone else there, is the user looking at someone off-camera, does the scene look normal?
- **Plain-English transaction explainer.** Gemini explains what the transaction actually does (for example, "this delegation lets X keep draining the wallet") for the display and for any second approver.
- **Incident reports.** For every decoy or alert, Gemini writes the report admins see on the Vultr dashboard.
- **Fear in the voice.** Gemini can judge vocal stress from a short audio clip. Onboard features (pitch, shake and speaking rate) are the fallback, and the default if we keep audio on the device.
- **Safeguards:**
  - **Fail closed:** no reply, a late reply or a malformed reply means the decoy key.
  - **Pinned HTTPS to Google**, so nobody can impersonate Gemini and send "all clear".
  - **The final decision and the keys stay on the STM32.** Gemini can't approve on its own: the PIN and the YubiKey touch are always required, and PINs are never sent.

## 4. MLH Best Use of Tiger Data

Tiger Data is PostgreSQL with time-series extensions (TimescaleDB). **With the mouse, YuDuino is a true time-series workload.** Before, we had one row per approval, a handful a day. Now the mouse streams **one row of aggregate features a minute, all day, for every person** (see [BASELINE.md](BASELINE.md)). That is exactly what a hypertable, continuous aggregates, compression and retention are for, so this is a much stronger fit than the one-row-per-approval version.

**The question Tiger Data answers:** "is this reading unusual *for this person, at this hour*?", fast enough to run in the middle of an approval.

| Tiger Data feature | What we use it for |
|---|---|
| **Hypertable** `readings(ts, user_id, grip_fraction, tremor, humidity, humidity_delta, temp, moisture, still_fraction, n)` | The continuous stream of per-minute feature rows, partitioned by time. **No raw sensor data, camera or audio.** |
| **Hypertable** `approvals(ts, user_id, features, gemini_score, decision, label)` | One row per approval, kept for the audit trail and false-alarm labels |
| **Continuous aggregates** | An **hourly** rollup per user (average, spread, sample count, min and max per feature), refreshed automatically. Per-user baselines by hour of day are then a fast read of a small table |
| **`time_bucket` queries** | At approval time: roll the last few minutes into a bucket and compare it with the user's baseline **for the same hour**, giving a z-score per feature in one query |
| **Compression policy** | Minute rows are compressed after a day or two, so a team's data stays small |
| **Retention policy** | **Raw minute rows are dropped after about 30 days; hourly aggregates are kept for months.** This is also our privacy promise: the fine detail doesn't linger |
| **Relational `users` table** in the same database | Consent, pause flag, enrolment date |

### How the pieces fit (SQL sketch)

This is a sketch to build from. Check the syntax against the Tiger Data docs on the day (names of the compression and columnstore calls have changed between versions).

```sql
-- the stream
CREATE TABLE readings (
  ts timestamptz NOT NULL, user_id text NOT NULL,
  grip_fraction real, tremor real, humidity real, humidity_delta real,
  temp real, moisture real, still_fraction real, n int);
SELECT create_hypertable('readings', 'ts');

-- hourly rollup per user, kept up to date automatically
CREATE MATERIALIZED VIEW readings_hourly WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS hour, user_id,
       avg(tremor) AS tremor_avg, stddev(tremor) AS tremor_sd,
       avg(humidity_delta) AS hum_avg, stddev(humidity_delta) AS hum_sd,
       avg(moisture) AS moist_avg, stddev(moisture) AS moist_sd,
       sum(n) AS n
FROM readings WHERE still_fraction > 0.5            -- quiet-hand rows only
GROUP BY 1, 2;
SELECT add_continuous_aggregate_policy('readings_hourly',
  start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '30 minutes');

-- keep detail short, keep summaries long
SELECT add_compression_policy('readings', INTERVAL '2 days');
SELECT add_retention_policy('readings', INTERVAL '30 days');
SELECT add_retention_policy('readings_hourly', INTERVAL '180 days');

-- at approval time: this person's usual for THIS hour of day (last 4 weeks) ...
WITH base AS (
  SELECT avg(tremor_avg) AS mu, avg(tremor_sd) AS sd, sum(n) AS n
  FROM readings_hourly
  WHERE user_id = $1 AND hour > now() - INTERVAL '28 days'
    AND extract(hour FROM hour) = extract(hour FROM now())),
-- ... against the last five minutes
now5 AS (
  SELECT avg(tremor) AS x FROM readings
  WHERE user_id = $1 AND ts > now() - INTERVAL '5 minutes' AND still_fraction > 0.5)
SELECT (now5.x - base.mu) / NULLIF(base.sd, 0) AS tremor_z, base.n FROM base, now5;
```

If `base.n` is too small, the guardian widens to the whole day and then the population prior (see [BASELINE.md](BASELINE.md#time-of-day-and-drift)). The z-scores go to Gemini with the camera frame; Gemini still decides, and the decision rule still fails closed. If we have the Tiger Data hyperfunctions, we can use medians (approximate percentiles) in the rollup instead of averages, to match the robust statistics in [BASELINE.md](BASELINE.md).

### What this buys us for the prize

- **A graph that fills in live:** the dashboard shows a person's tremor and humidity by hour of day appearing over the day. The continuous aggregates drive it.
- **Real time-series features:** hypertable, continuous aggregates, compression, retention and `time_bucket` all used for a reason, not for show.
- **A privacy story built from database settings:** raw rows expire, aggregates remain.
- **Same database as before:** the audit log mirror, false-alarm labels (thresholds are tuned from them), and the live dashboard are unchanged.

## Overlapping sponsor challenges

Seen in the opening ceremony slides. We have a limited team and a lot of tracks, so the **recommended effort** is small for each.

| Sponsor and challenge | Fit | Effort | What to do |
|---|---|---|---|
| **SGX FX:** "Protect your assets from a trading market storm": stay safe, early warning, predict, spot opportunities. They provide historical pricing data; any data may be used | **Good.** "Keep traders' money safe when things get rocky" and "early warning" match the operator-state idea | Small, only if the pricing data is easy to get | The **tilt guard**: a market-storm regime from their data combined with the operator's state from the mouse, raising step-up and alerting a risk manager ([INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md#tilt-guard-operator-state-meets-market-state-an-idea-for-sgx-fx-and-this-brief)). Keep it an early warning to a human, not a prediction |
| **Neptune North:** "Actors work better together": several actors with a common goal, independent decisions, and **resilience when communications fail** | **Partial.** Each mouse's STM32 decides locally and **fails closed** when it can't reach the guardian; several people's approvals compose (second approver) | Mention only | Say it in the pitch. A real **offline mode** is an open design problem: no trusted clock for nonces, no Gemini offline, so only onboard rules; pre-issued nonces or queued signed envelopes would be needed. Don't build it tonight |
| **Accenture:** "Identify a frustrating process people accept as 'just the way things work' and redesign it with AI and LLMs" | **Framing only** | None | One sentence: people accept PINs, codes and pop-ups as how security works; we remove them and let AI do the checking |
| **QRT: Tagged** | **Direct**, already a target | As planned | The aggregated hand is the language |
| **RS Group: sense, analyse, respond** | **Direct**, already the hardware main | As planned | See section 1 |

**Recommended order of effort:** (1) the working mouse flow, the owner check and the dashboard, which serve Composition, RS, Marshall Wace and Tagged at once; (2) Tiger Data and Gemini, already in the plan; (3) the music angle (about two hours); (4) Vultr and ElevenLabs; (5) the tilt guard only if SGX's data is quick to use; (6) everything else is a sentence in the pitch. Don't spread thinner than that.

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

1. **Mouse shell** that hides the whole device: the UNO Q with a frosted window over the LED matrix, three finger keys over the Modulino Buttons, and palm pads over the touch, moisture and Thermo sensors. Layout and trade-offs: [MOUSE-DESIGN.md](MOUSE-DESIGN.md).
2. **Dock** for the USB-C hub, camera and YubiKey.
3. **Camera mount** at face height.

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
