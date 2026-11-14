# YuDuino: prototype and development plan

*Written 14 November 2026, about 19:15 on day one of DurHack.* Back to the **[overview](YuDuino-Overview.md)** · **[challenge plan](CHALLENGES.md)** · **[hardware plan](HARDWARE-PLAN.md)**

## How this plan works

We build in **waves**. Every wave moves **all three tracks forward together**: hardware, cryptography, and the extensions (Gemini, Tiger Data, Vultr, ElevenLabs, 3D printing, then the stretch goals). Each wave slightly redesigns all three, so at the end of every wave we have a **working, demoable YuDuino**, just a richer one than before.

- **Wave 1 is a minimal end-to-end prototype.** It's ugly, but it goes from request to verdict to signature.
- **Each later wave adds one layer across all three tracks.** Nothing is built in isolation and then bolted on at the end.
- **If time runs out, we stop after any wave and still have a working demo.** Stretch goals live only in the last wave.

**Keep it simple.** Gemini alone does the duress calculation. The device fails closed: no reply, a late reply or a malformed reply means the decoy, over pinned HTTPS to Google. There is no second onboard calculation.

**Timing assumption:** about 16 hours of building left (19:15 Saturday to roughly 11:00 Sunday, before judging). If the deadline is different, shrink or stretch Wave 3 and Wave 4, never Waves 1 and 2.

## The waves at a glance

| Wave | Time (approx.) | Goal | Demo when done |
|---|---|---|---|
| **1. Skeleton** | 19:30 to 23:30 | One approval end to end, with the simplest version of every part | A request appears on the LED matrix; PIN, YubiKey tap, Gemini verdict, real or decoy signature, the verifier accepts or freezes |
| **2. Real signals** | 23:30 to 03:30 | Every sensor feeds the "language"; baselines per user; keys move to the microcontroller | Calm vs. stressed approval gives different verdicts, and the usage appears in Tiger Data |
| **3. Response and polish** | 03:30 to 07:30 | A real-world response: alerts, incident reports, a printed device | A decoy fires a Telegram alert, a Gemini-written incident report on the Vultr dashboard, and frozen funds |
| **4. Harden and stretch** | 07:30 to 10:30 | Post-quantum signature, rehearsed demo, stretch goals if time | Full Binance-replay demo, rehearsed twice, with a backup video |
| **Submit** | 10:30 to 11:00 | Devpost, README, video | Submitted |

## Wave 1: skeleton (minimal end-to-end prototype)

**Goal:** prove the whole loop works once, with the simplest version of every part.

| Track | What we build |
|---|---|
| **Hardware** | UNO Q, USB-C hub, power, camera. LED matrix as the display. Modulino Buttons for PIN, approve and reject. Modulino Movement and the touch sensor on a breadboard (no grip yet). YubiKey plugged into the laptop. |
| **Cryptography** | Follow the **[YuSeal design](CRYPTO.md)**: the STM32 hashes exactly what it shows and makes a **tag** after the PIN; the YubiKey signs the same digest; ML-DSA-65 seals it all, with **one key** (no separate decoy key; the duress status is inside the tag). The guardian checks all three and either "executes" or "holds". Code is ready: see the **[build flow](BUILD-FLOW.md)**. |
| **Extensions** | **Gemini:** one call with tremor and touch features plus one camera frame, returning `{duress, score, reasons}` as JSON, with a timeout that fails closed to the decoy. Results are logged to a local JSON file. **3D printer:** start printing the grip (it takes hours). |

**Done when:** a fake transfer request scrolls on the LED matrix; we enter the PIN and tap the YubiKey; Gemini returns a verdict; a calm approval executes, and pulling the network cable gives a decoy that the verifier freezes.

## Wave 2: real signals

**Goal:** every sensor becomes part of the hidden language, and each user's baseline makes the translation personal.

| Track | What changes |
|---|---|
| **Hardware** | Add Modulino Thermo, the moisture sensor, and microphone audio. Everything moves into a **cardboard grip**. Add a one-minute **enrolment** recording of the user's calm baseline. |
| **Cryptography** | Move the real and decoy keys to the **STM32 microcontroller side**: Linux sends the verdict, the STM32 chooses which key signs. Add nonce and expiry checks to the verifier (replays fail). Start the **hash-chained audit log** (each entry includes the previous entry's hash). |
| **Extensions** | **Tiger Data:** one row per usage (feature scores, verdict, decision), with a continuous aggregate for each user's baseline. Gemini now gets every feature as a delta from that baseline. **Vultr:** stand up the server and move the verifier onto it, with **pinned HTTPS** for the Gemini call. **3D printer:** collect the grip; start the UNO Q enclosure and YubiKey dock. |

**Done when:** the same person approving calmly and then while shaking and breathing fast gets different Gemini verdicts with sensible reasons; both usages appear in Tiger Data; replaying an old approval is rejected.

## Wave 3: response and polish

**Goal:** the system responds in the real world, and the device looks like a product.

| Track | What changes |
|---|---|
| **Hardware** | Cardboard mock-up, then the **3D-printed mouse shell** ([MOUSE-DESIGN.md](MOUSE-DESIGN.md)), with the YubiKey moved from the laptop into the dock (the hub the mouse's cable plugs into) (stretch: if USB access is blocked, keep it on the laptop). Camera on a printed mount. Tidy the wiring. |
| **Cryptography** | The verifier on Vultr becomes the only route to "execute" (no back door). Show the audit log chain on the dashboard and check it on load. YubiKey **attestation** check at enrolment, so only genuine YubiKeys can register. |
| **Extensions** | **Vultr response engine:** on a decoy, alert the on-call team via Telegram or email, escalate if nobody acknowledges, freeze funds, and require a second approver. **Gemini** writes the incident report and the plain-English explanation of the transaction. **Admin dashboard** with live charts from Tiger Data and the incident reports. **ElevenLabs** reads the transaction aloud. |

**Done when:** a coerced approval looks normal on the device, while within seconds a phone receives a Telegram alert and the dashboard shows a Gemini-written incident report and frozen funds.

## Wave 4: harden and stretch

**Goal:** make the demo bulletproof, add the post-quantum layer, and take stretch goals only if everything above is solid.

| Track | What changes |
|---|---|
| **Hardware** | Sealed shell screws (tamper evidence). Spare cables and a backup power bank. Label the parts for judges (the "hackiest hack" angle). |
| **Cryptography** | The ML-DSA signature and the STM32 tag are already in Wave 1 (see [CRYPTO.md](CRYPTO.md)). Wave 4 hardens: lock the STM32's debug port, SLH-DSA root, confirm hybrid post-quantum TLS. Moving the ML-DSA key itself onto the STM32 is future work. |
| **Extensions** | Rehearse the **Binance-replay demo** twice and record a backup video. **ElevenLabs** calm and scared test voices for a reliable voice demo. **Stretch, if time:** Solana devnet wallet program (a valid signature releases funds, a decoy freezes them); MongoDB Atlas for profiles, policies and incidents. **DEV** write-up after the weekend. |

**Done when:** the full demo runs start to finish without touching a laptop, twice in a row, and the backup video is saved.

## Who does what (team of 4)

The same split across every wave, so each person always owns one slice of all three tracks:

1. **Microcontroller and sensors:** STM32 sketch, sensor features, keys on the STM32 side.
2. **Linux side and Gemini:** camera, audio, the Gemini call, fail-closed handling.
3. **Crypto and backend:** WebAuthn, verifier, audit log, Vultr, Tiger Data.
4. **Build and pitch:** grip, 3D printing, dashboard look, demo script, video.

## Rules for every wave

- **End every wave with a working demo.** If something isn't working by the end of its wave, cut it, don't extend the wave.
- **Commit at the end of each wave** with a tag (`wave-1`, `wave-2`, ...), so we can always fall back to the last good version.
- **Never trust the laptop.** The display and the signatures come from the device; the verifier only trusts signatures.
