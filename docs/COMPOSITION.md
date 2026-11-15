# Composition: YuDuino as the theme

DurHack 2026's theme is **Composition**: *"We want to see creativity! Explore art, music and tech! We want to see idea mixing and trying new combinations!"* Judging: **Creativity & Innovation, Technical Competence & Execution, Research & Learning, Polish & Completion** (from the opening ceremony slides).

This page says how YuDuino is a composition and maps the project to each judging criterion. It is the framing for the overall prize. The sponsor tracks are in [CHALLENGES.md](CHALLENGES.md).

## The idea: many meaningless signals, composed into one

**Composition = putting separate parts together so the whole means something none of the parts do.** YuDuino does that at every level:

| Level | Parts | What the composition says |
|---|---|---|
| **The signal** | tremor, sweat, humidity, temperature, grip, click timing, movement style, camera, voice | Each reading means nothing alone (a shaky hand might be coffee). Together they say **who is holding the mouse** and **whether they are acting freely** |
| **The proof** | a YubiKey signature, the STM32's tag, an ML-DSA post-quantum seal | Three independent proofs composed into one approval |
| **The object** | a **mouse** + a **YubiKey** + **AI** (an on-device Edge Impulse model) + a **time-series database** | A new combination: an everyday object that is secretly an authenticator |
| **The history** | a day of minute-by-minute readings | A person's habitual "piece": their baseline, hour by hour |

The attacker sees readings but not what they add up to. That is the project's core idea ([README](../README.md#the-vision-a-language-the-attacker-can-never-read)), now with a name.

## Mapping to the judging criteria

| Criterion | How YuDuino answers it | Make sure we show |
|---|---|---|
| **Creativity & Innovation** | An authenticator hidden in a mouse that works with **no input at all**; passive behavioural identity that quietly rejects other hands; misdirection (even the logs mislead) | The mouse working as a mouse, then the borrowed-mouse and coerced demos |
| **Technical Competence & Execution** | Tested crypto (ML-DSA-65, HMAC tags, hash-chained log) with the real C++ checked against Python byte for byte; STM32 and Linux split; an all-day on-device baseline | The test run, the dashboard filling with real rows |
| **Research & Learning** | A written design brief, a v1 to v2 review, 20 honest weak spots, a test plan that measures the owner check, and the honest list of what mouse mode gives up | The docs, and real error numbers from the owner-check test |
| **Polish & Completion** | A donor mouse that looks and works like a mouse, a live dashboard, a rehearsed demo, a recorded backup | A shell that survives being handed to a judge |
