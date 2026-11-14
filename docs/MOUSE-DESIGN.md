# YuDuino in a mouse

Design change (Jonah, 2026-11-14): the whole device is hidden inside a **computer mouse**, so it looks like something nobody would look at twice. This page says how each part maps onto a mouse, what the layout is, how the 3D-printed shell works, and what we give up.

**One rule first.** Hiding the device is *obscurity*, not security. All the security still comes from the three proofs in [CRYPTO.md](CRYPTO.md). If someone finds out the mouse is the device, nothing breaks. The mouse only stops people noticing it, and makes the grip more natural.

Sizes below are approximate. **Measure the real parts before you print.**

## The short version

| Question | Answer |
|---|---|
| Is it a working mouse? | **No, by default.** It's a mouse-shaped shell. It doesn't move a cursor, and it is **not** a USB mouse to any computer. (Stretch option B below makes it a real one.) |
| Where is the UNO Q? | Flat in the base, with the LED matrix facing up under a small frosted window. |
| What is the display? | Still the **UNO Q LED matrix**, seen through the window. A hidden device can't have a screen you can't see, and the "screen shows exactly what you approve" rule stays. |
| Where do the PIN buttons go? | The Modulino Buttons sit under three printed finger keys at the front, where index, middle and ring fingers rest. |
| What is on the palm? | The touch pad (grip gate), the moisture pads, and a vented pocket for the Thermo. |
| Where are the camera and YubiKey? | **Outside the mouse**, in a small **dock** (the Arduino USB-C hub) that the mouse's cable plugs into. |
| What does the mouse cable do? | Carries power and USB from the dock. The UNO Q talks to the guardian over its own Wi-Fi, so no data goes through a laptop. |

## How the sensors map onto a mouse

A resting hand on a mouse is the most natural grip there is, so the signals get *better* than on the handheld grip we planned before: the palm is always in the same place.

| Signal | Part | Where in the mouse | Notes |
|---|---|---|---|
| **Grip held** | DFRobot touch sensor (D2) | Under the **palm hump**, behind a thin wall (about 1 to 1.5 mm; capacitive sensors read through plastic) | Gates the PIN: presses only count while it reads held, as before |
| **Sweat and contact** | DFRobot moisture sensor (A1) | Two exposed **copper tape pads** flush with the shell where the **palm heel** and the **thumb base** touch | Add a 1 kΩ resistor in each pad line (see ESD below) |
| **Palm humidity and temperature** | Modulino Thermo | In a **vented pocket** under the hump: a grille of 1 mm holes. **Keep it as far as possible from the UNO Q**, with an air gap | The board heats the shell, so absolute temperature drifts. The **humidity change** is the useful signal |
| **Tremor** | Modulino Movement | Screwed **rigidly to the shell**, not floating loose and not on the UNO Q | See "Tremor on a mouse" below |
| **PIN** | Modulino Buttons | Under three **printed keys** at the front | Short press = `A B C`, press held 0.8 s or more = `a b c`. These are not HID mouse buttons, so clicking them does nothing to any computer |
| **Face, scene, voice** | USB camera with mic | **Outside**, on the monitor or the dock | Still needed for the challenge. It isn't hidden; the mouse hides the *trusted device*, not the camera |

### Tremor on a mouse

A mouse sits on a desk, so the accelerometer sees the desk too. Two rules:

1. **Only read tremor while the mouse is still** (the PIN is typed on a still mouse anyway). If the shake is large and slow, that is *someone moving the mouse*, not tremor: the window is ignored.
2. **Filter to the tremor band** (about 4 to 12 Hz) and **ignore 100 ms around each key press**, so the click itself isn't counted as a shake. This is a Wave 2 code change in `sketch.ino` (`shakeRms`); today it only removes the average.

## Layout

Top view, **front (fingers)** at the top. Mouse shell about **115 × 65 × 38 mm**; UNO Q board about **69 × 53 mm**.

```
        front (away from you)
   ┌───────────────────────────┐
   │  [ key A ][ key B ][ key C ] │  ← three printed keys over the Modulino Buttons
   │   ┌───────────────────┐   │
   │   │  frosted window   │   │  ← LED matrix underneath: shows the request, then OK
   │   └───────────────────┘   │
   │     ╭───────────────╮     │
   │     │  palm hump    │     │  ← touch pad (inside), moisture pads (flush)
   │     │  vent grille  │     │  ← Thermo pocket under it
   │     ╰───────────────╯     │
   └─────────────┬─────────────┘
                 │  USB-C cable (thin) ──► dock: hub + camera + YubiKey
        back (towards you)
```

Side view, the stack from the bottom:

1. **Base plate**: the UNO Q on four M2.5 standoffs (the UNO form factor mounting holes; check yours).
2. **Qwiic cables** (short, 5 to 10 cm) run up to the Buttons (front), Movement (screwed to a printed boss), and Thermo (far end, in its pocket).
3. **Top shell**: window over the matrix, keys over the Buttons, hump over the touch pad, vent grille, cable notch at the back.

The **USB-C port** faces the rear so the cable leaves where a mouse cable does. The board's **Wi-Fi antenna** should not sit under the palm (a hand detunes it): note where it is and test Wi-Fi signal with a hand on the mouse.

## The display problem (the big one)

The rule is that the screen must show exactly what you approve. A hidden device still needs a visible display. Our answer:

- The **LED matrix** shows through a window of **thin natural PLA** (0.8 to 1 mm, which diffuses the LEDs) or a cut-out covered with frosted tape. It is **dark except during an approval**, so nobody sees it light up unless they are looking at your mouse while you're approving.
- **The risk is readability.** The matrix is only 8 × 13 and scrolls. With a hand on the mouse, the window sits just behind the knuckles. **Cardboard-test this first** (see the build order) before printing anything. If your hand blocks it, move the window and the keys until you can read it comfortably with the hand resting.
- **Fallbacks, in order:** (1) lift the fingers off the keys to read, then press (the 90 s timeout allows it); (2) put the window on the thumb side; (3) a small HDMI screen at the dock, the same trusted-display slot as in the hardware plan (it's wired to the board, not to the laptop).
- **Not acceptable:** showing the text on the laptop screen, or reading it out through the laptop. The laptop is exactly the thing we don't trust. (ElevenLabs reading the request aloud stays an accessibility extra, never the check.)
- If the text is **upside down**, rotate the board 180° in the shell. The matrix call for rotation is unverified.

## Shell and 3D printing

- **Two parts:** base plate and top shell, joined by four small screws at the corners, hidden under the cable notch and rubber feet. Seal the screws with a dot of paint so tampering shows.
- **Print the top shell upside down**, so it needs no supports. The base prints flat. PLA, 0.2 mm layers, about 3 perimeters. The size is large for a hobby bed; check the printer's bed first, and plan a few hours of printing, so start it early.
- **Features to model:** four standoffs; slot for the Modulino Buttons board; three key caps with a small stop so they can't fall out; a window opening with a 1 mm skin; a thin 1.2 mm wall over the touch pad; palm pad recesses for copper tape; the vent grille; a screw boss for the Movement board; the cable notch with a strain relief (a knot or zip-tie inside).
- **Look:** a smooth ergonomic profile and a matte finish. Rubber feet at the corners and a light sand and paint finish make it look like it came from a shop.
- **Option B (after the demo works): a donor mouse.** Buy a cheap real mouse, keep its shell, buttons and wheel, and fit the YuDuino inside. Its own cable and circuit board still plug into the laptop, so it works as a real mouse. **Never connect the two boards electrically.** This is the most convincing version, but it is tight, so only try it once the printed shell works.

## Security trade-offs (please read)

| # | Trade-off | Why it matters | What we do |
|---|---|---|---|
| 1 | **Secret device vs visible display** | A device nobody notices still needs a window you can read | Window over the matrix, lit only during an approval; cardboard test first; fallbacks above |
| 2 | **Hiding is not protection** | Anyone who opens it finds an ordinary UNO Q | Security stays in the crypto. Sealed screws show tampering. Wave 4 still locks the STM32 debug port ([weak spot 2](CRYPTO.md#remaining-weak-spots)) |
| 3 | **A look-alike mouse swapped in** | A fake could show a different text to you | It can't produce a valid tag (it lacks `K_MCU`), and the guardian re-renders the text itself, so the worst outcome is a refused approval, not a forged one |
| 4 | **The YubiKey is in the dock, not the mouse** | You touch it in two places (buttons on the mouse, YubiKey at the dock) | Put the dock at the desk edge. This also means the YubiKey is *not* hidden |
| 5 | **The camera isn't hidden** | An attacker can see a camera and know duress is judged | The strongest signal is still the duress PIN, which the camera doesn't affect |
| 6 | **Static from your hand (ESD)** | Bare pads on the palm can reset or damage the board, which in a demo looks like a crash | 1 kΩ series resistors on both pad lines; test after shuffling on carpet |
| 7 | **Heat in a closed shell** | The UNO Q warms the shell, so temperature readings drift and the palm gets warm | Thermo far from the board; vent grille; rely on humidity change; baseline per device |
| 8 | **Wi-Fi is weaker inside a palm** | A failed guardian call fails closed (duress), so a weak signal looks like an alarm | Check signal with a hand on the mouse; keep the antenna end clear of the palm |
| 9 | **A mouse that isn't a mouse** | Someone may pick it up and find the cursor doesn't move | Keep it on the desk like a spare mouse, or build Option B so it really works |
| 10 | **Cable and dock are not secret** | A thick cable to a hub gives it away | Use a thin USB-C cable; hide the dock behind the monitor |
| 11 | **Pressing keys on a mouse looks normal** | This is a *gain*: PIN presses look like clicks, and a long press for the duress PIN is hard to notice | Keep both PINs short enough to type fast, and test that long presses are easy to do blind |
| 12 | **Reading while holding** | Awkward reading slows approvals | The session timeout is 90 s; keep requests short (96 characters maximum) |

## Build order (before printing)

1. **Cardboard mock-up (20 min).** Cut a mouse-sized shape from cardboard. Put the UNO Q, Buttons and Thermo in place with tape. **Hold it. Can you read the matrix? Can you press A, B, C and a long press without moving the board?** Adjust positions. Photograph the layout.
2. **Run the whole demo from the cardboard mock-up** (the Milestone 1 steps in [HARDWARE-PLAN.md](HARDWARE-PLAN.md)). If it works, the electronics are done.
3. **Measure and model.** Measure each part with calipers or a ruler, make the model, print the **base plate first** as a fit test (it's quick), then the top shell.
4. **Assemble** with short Qwiic cables, copper pads, resistors, and the cable strain relief. Re-run Milestone 1 inside the shell.
5. **Test the mouse specifics:** matrix readable with a hand on; Wi-Fi signal with a hand on; touch pad reads 1 only when the palm is there; moisture rises on a damp palm; tremor window ignores desk movement; shake the mouse and check the PIN still works.

## What changes in the code

Nothing breaks. Small changes, all in Wave 2 and later:

- **`sketch.ino`:** filter tremor to 4 to 12 Hz, and skip the window while the mouse is moving or for 100 ms around a key press (`shakeRms`). Possibly rotate the matrix text.
- **Veto rule:** check `onboard_veto` in `approve.py` against mouse use. Large slow movement means "the mouse was moved", not duress, so it must not trigger the veto.
- **No new crypto.** The three proofs, the PIN rules and the decision rule are unchanged.
