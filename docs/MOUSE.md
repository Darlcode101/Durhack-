# YuDuino as a mouse

**Status:** proposal, 14 November 2026. Not built yet. The crypto (YuSeal, keys, verifier) doesn't change; this changes where the sensors live and where the baselines come from.

## The idea

Put the sensors inside an ordinary-looking wired mouse.

- **All day,** it quietly learns what *normal* looks like for its owner: grip, sweat, tremor, temperature, how they move and click.
- **When an approval is needed,** the same mouse is the input: the PIN is a click pattern on the side buttons, then a YubiKey tap. The system compares *this moment* with *the owner's own behaviour a few minutes ago*.

Someone standing behind the user sees a person using a mouse.

It fixes the two biggest weaknesses of the handheld grip: **too little data** (a 30-second enrolment baseline) and **an obvious security gadget**.

## Hardware: where everything goes

The UNO Q won't fit in a mouse, so it's split in two:

```
 ┌──────── mouse shell (3D-printed, or a gutted cheap mouse) ────────┐
 │  thumb side: Modulino Buttons  → look like normal side buttons     │
 │  palm hump:  Modulino Thermo   → palm temperature + humidity       │
 │  palm pad:   touch sensor      → "is it being held?"               │
 │  grip sides: 2 copper-tape pads → skin conductance (sweat), A1     │
 │  inside:     Modulino Movement → hand tremor + movement dynamics   │
 │  original mouse electronics → USB to the computer as usual         │
 └───────────────┬────────────────────────────────────────────────────┘
                 │ one cable sleeve: mouse USB + Qwiic + 3 jumpers
          under the desk: UNO Q + hub + YubiKey + camera on the monitor
```

| Part | Where | Why |
|---|---|---|
| Original mouse PCB | Inside, unchanged | Still moves the pointer; building a real mouse from scratch is a hackathon in itself |
| Modulino Buttons | Thumb side | Look like normal side buttons; PIN entry |
| Modulino Thermo | Under the palm | Palm temperature and humidity |
| Touch sensor (D2) | Under the palm pad | Data is only collected while the mouse is actually held |
| Copper-tape pads (A1, via a resistor) | Both grip sides | Real skin conductance (GSR), replacing the soil-moisture probe, which never measured skin well |
| Modulino Movement | Base | Tremor, and how the mouse is moved |
| UNO Q, hub, YubiKey | Under the desk or in a "mouse dock" | Out of sight; the camera stays on the monitor |

- Modulinos are about 41 × 25 mm, so they need a large printed shell, not a slim one. Thermo and Buttons matter most inside it.
- **Trade-off:** the LED matrix trusted display is no longer under the user's nose. Either mount the dock where it's visible, or accept the approval text on screen (weaker: the laptop isn't trusted).
- The **Free 3D printer** track: a printed mouse shell with Modulino mounts.

## Three modes

### 1. Passive learning (all day)
- While the touch sensor says the mouse is held, the STM32 computes features every few seconds: tremor, skin conductance, palm temperature and humidity, movement speed, jerkiness, click timing.
- Only those **summary numbers** are kept. No raw streams, no camera frames.
- They build **per-user baselines by time of day**: a real time series of thousands of points a day, which is what the Tiger Data plan needs.

### 2. Continuous "is this the owner?" check
- Mouse movement and clicking are fairly personal (*mouse dynamics*).
- **Not reliable enough to authenticate anyone on its own**, but a useful risk signal: if an approval arrives while the movement doesn't look like the owner, ask for more proof.

### 3. Approval
1. A request arrives.
2. The user holds the mouse and enters the PIN on the side buttons. The duress PIN is the same presses with one held longer, so an observer sees nothing different.
3. YubiKey tap.
4. Gemini compares the approval moment with **the user's last 10–15 minutes of normal use**. "Is Alex more stressed than Alex was five minutes ago?" is a far easier and more accurate question than "is this person stressed?"
5. Real approval or decoy, exactly as in [CRYPTO.md](CRYPTO.md).

## Why it's better

- **Much more data, so much better baselines.** Most of the weakness in duress detection comes from not knowing what normal looks like for this person right now.
- **Hidden in plain sight.** Nobody even sees a device.
- **No new habits** until an approval comes up.

## Cautions

- **Don't rely on secrecy.** Hiding the device is a bonus, not the security. The system must stay safe even if the attacker knows the mouse is special: the PIN, YubiKey and signatures are the proof. Say this before a judge asks.
- **This is all-day monitoring of someone's body.** Skin conductance and tremor over time are health-adjacent data (special category under UK/EU GDPR):
  - process and keep it on the device
  - store summaries only
  - let the user see and delete it
  - send Gemini a summary **only at approval time**, never the all-day stream
- **"Only the user knows" must mean the user fully consents.** The same device deployed by an employer would be covert employee surveillance. Pitch it as the user's own protection, owned and controlled by them.
- **Normal days are noisy.** Deadlines, gaming and caffeine move every signal. Comparing with the last 15 minutes helps, but false alarms will happen, so the response stays a decoy or step-up, never a lockout.

## Demo

1. Use the mouse normally for a minute while a live dashboard shows "your normal" forming.
2. Approve calmly: real approval.
3. A teammate "forces" an approval (duress PIN or real stress): the screen says approved; the verifier freezes it and alerts.

**The line to land:** "There's no security device on this desk. It's the mouse."

## Open questions

- [ ] Gut a real mouse, or print a shell around one?
- [ ] Where the trusted display goes (dock on the desk vs on-screen)
- [ ] How long the cable sleeve can be before the Qwiic bus gets unreliable (Qwiic is meant for short runs)
- [ ] Which features to log, and how often, so baselines are useful without storing more than needed
