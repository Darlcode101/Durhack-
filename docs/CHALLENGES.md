# YuDuino: challenges and result

*What we entered at DurHack 2026 and how it went. Updated 16 November 2026, after the event.*

Back to the **[README](../README.md)** · **[overview](YuDuino-Overview.md)** · **[pitch deck](../presentation/YuDuino-DurHack-2026-pitch.pdf)**

## Result

**2nd place in the RS / Arduino track.** Presented by Jonah and Alex.

## RS / Arduino: sense, analyse and respond to the real world

The brief asked for an intelligent system that captures data, analyses sensor inputs, makes a decision and triggers an action, using the UNO Q, a camera and a USB hub. YuDuino follows those four steps:

| Step | What YuDuino does | Parts |
|---|---|---|
| **Sense** | Every minute the mouse is used, it records how you grip, move, sweat and click, but only while your hand is on the mouse. That builds a personal per-hour baseline on the device | Modulino Movement and Thermo, DFRobot touch and moisture, the mouse's own click, USB camera |
| **Analyse** | Only when you click to make a transaction: your last minute is compared against your baseline (z = (x − μ) / σ), and a locally hosted K-means anomaly model uses all the channels together | UNO Q (STM32 for sensors and baseline, Linux side for the model and camera) |
| **Decide** | Normal: a real approval. Duress: a decoy approval that looks identical. Someone else's hand: a quiet, ordinary-looking rejection | STM32 makes the final call |
| **Act** | Releases a sealed signature (never an "OK"); the customer's verifier reads the hidden status | YubiKey, STM32 tag, ML-DSA seal |

All three mandatory parts are used: **UNO Q** (the brain), **camera** (the over-the-shoulder rule), **USB-C hub** (power, camera, YubiKey).

## Framing

- **Overall theme: Composition.** Many readings that mean nothing alone, composed into one verdict ([COMPOSITION.md](COMPOSITION.md)).
- **Audience: transaction desks** (we framed it for Marshall Wace's "New Worlds"; [INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md)). The claim is a new combination of known parts, not a first ([PRIOR-ART.md](PRIOR-ART.md)).

## Not built

The add-ons and stretch goals from our weekend plan were not built: ElevenLabs readback, a Solana devnet wallet, and MongoDB Atlas (we chose no cloud database: all user data stays on the device).
