# Composition: YuDuino as the theme

DurHack 2026's theme is **Composition**: *"We want to see creativity! Explore art, music and tech! We want to see idea mixing and trying new combinations!"* Judging: **Creativity & Innovation, Technical Competence & Execution, Research & Learning, Polish & Completion** (from the opening ceremony slides).

This page says how YuDuino is a composition, suggests a music angle, and maps the project to each judging criterion. It is the framing for the overall prize. The sponsor tracks are in [CHALLENGES.md](CHALLENGES.md).

## The idea: many meaningless signals, composed into one

**Composition = putting separate parts together so the whole means something none of the parts do.** YuDuino does that at every level:

| Level | Parts | What the composition says |
|---|---|---|
| **The signal** | tremor, sweat, humidity, temperature, grip, click timing, movement style, camera, voice | Each reading means nothing alone (a shaky hand might be coffee). Together they say **who is holding the mouse** and **whether they are acting freely** |
| **The proof** | a YubiKey signature, the STM32's tag, an ML-DSA post-quantum seal | Three independent proofs composed into one approval |
| **The object** | a **mouse** + a **YubiKey** + **AI** (Gemini) + a **time-series database** | A new combination: an everyday object that is secretly an authenticator |
| **The history** | a day of minute-by-minute readings | A person's habitual "piece": their baseline, hour by hour |

The attacker, like a listener who can't read music, sees notes but not the piece. That is the project's core idea ([README](../README.md#the-vision-a-language-the-attacker-can-never-read)), now with a name.

## The music angle: the hand's score

**Suggestion:** render the live sensor stream as **music**, so a judge can *hear* the difference between an owner, an impostor and a coerced approval. It belongs on the **dashboard** (hosted on Vultr) and in the demo, **never on the mouse**, which stays silent so it keeps looking like a mouse.

**The mapping (a starting point, change it by ear):**

| Signal | Voice | How it sounds |
|---|---|---|
| Grip held | a sustained pad chord | present while the palm is down; fades when released |
| Tremor (4 to 12 Hz power) | a low drone with vibrato | calm = steady; trembling = a wobble that widens |
| Palm humidity and moisture | a slow filter sweep on the pad | dry = dark; damp = brighter and breathier |
| Temperature | the key or register | stays in the person's usual register; drifts out of it when odd |
| Clicks | percussion | each click is a soft hit; its length and double-click gap shape the rhythm |
| Movement style | a melodic line | smooth = flowing; jerky = broken phrases |
| Owner distance | harmony | the owner's hand is **consonant** with their own baseline; a different hand is **dissonant**; the baseline itself is the "key" |
| Duress score | a tension note | a minor second or tritone enters as the score rises |

So an owner's session is a steady, consonant piece. A borrowed mouse sounds **out of tune** straight away. A coerced approval adds tension. The **baseline is the key signature** the live notes are measured against, and a day of data can be shown as a **score** (a staff with hours across it, and deviations as accidentals).

**How to build it cheaply:** the browser's built-in **Web Audio API** (no dependency), driven from the dashboard's live feed of aggregate features; or a small library such as Tone.js. About 100 lines. If ElevenLabs offers a music or sound-effects API on the day, it could generate a bed, but check; the Web Audio version needs nothing external. **Not built yet.**

**Honest caveats.** It is a presentation and sense-making tool, not a security control. Sonifying the *aggregates* (not raw data) keeps the privacy promise ([BASELINE.md](BASELINE.md#privacy)). Don't claim it detects anything the checks don't; it makes them audible.

## Mapping to the judging criteria

| Criterion | How YuDuino answers it | Make sure we show |
|---|---|---|
| **Creativity & Innovation** | An authenticator hidden in a mouse that works with **no input at all**; passive behavioural identity that quietly rejects other hands; misdirection (even the logs mislead); sonification of the hand | The mouse working as a mouse, then the borrowed-mouse and coerced demos |
| **Technical Competence & Execution** | Tested crypto (ML-DSA-65, HMAC tags, hash-chained log) with the real C++ checked against Python byte for byte; STM32 and Linux split; Tiger Data time-series (hypertable, continuous aggregates, retention) | The test run, the dashboard filling with real rows |
| **Research & Learning** | A written design brief, a v1 to v2 review, 20 honest weak spots, a test plan that measures the owner check, and the honest list of what mouse mode gives up | The docs, and real error numbers from the owner-check test |
| **Polish & Completion** | A donor mouse that looks and works like a mouse, a live dashboard, a rehearsed demo, a recorded backup | A shell that survives being handed to a judge |

## The demo as a composition

1. **Silence.** Hand a judge the mouse. It is a mouse. Say nothing.
2. **The piece.** Show the dashboard playing *your* session: steady and consonant.
3. **Another hand.** The judge uses it. The dashboard goes out of tune, the approval fails like any ordinary glitch, one quiet alert fires.
4. **Under pressure.** You click with a shaking hand and a second face in frame. The approval is "accepted", nothing moves, tension enters the music.
5. **The proof.** Show the signed, hash-chained log; tamper with a line and watch it fail.

## What to build for this (small)

| Item | Where | Effort |
|---|---|---|
| Live feed of aggregate features to the dashboard | guardian | needed anyway |
| Sonification (Web Audio) | dashboard | about two hours, Wave 3 |
| "Score" view of a day (hours across, deviations marked) | dashboard | optional, if time |
| A one-line "composition" framing in the pitch and write-up | docs, DEV post | minutes |
