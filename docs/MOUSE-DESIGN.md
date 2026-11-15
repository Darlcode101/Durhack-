# YuDuino in a mouse

Design (Jonah, 2026-11-14): the whole device is hidden inside a **computer mouse that works exactly like a normal mouse**. No screen, no PIN, no extra gesture. The user just uses their mouse. This page covers the hardware: how each part maps onto a mouse, the layout, the 3D-printed or donor shell, and the physical trade-offs.

How the approval works with no input: [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md). How the mouse tells the owner from anyone else: [OWNER-CHECK.md](OWNER-CHECK.md). How it learns all day: [BASELINE.md](BASELINE.md).

**Three reasons for a mouse.**
1. It **hides** the device: nothing on it looks like an authenticator (no screen, no PIN pad).
2. It is **held all day**, so it passively learns this person's normal grip, tremor, sweat and temperature ([BASELINE.md](BASELINE.md)). That is learning only: duress is judged only at the moment of a transaction.
3. It can tell **whose hand** is on it, and quietly reject anyone else ([OWNER-CHECK.md](OWNER-CHECK.md)).

**One rule first.** Hiding the device is obscurity, not security. If someone works out the mouse is the device, nothing breaks, because the checks don't depend on secrecy. The mouse mostly stops people *noticing* it, and makes its measurements natural.

Sizes below are approximate. **Measure the real parts before you print.**

## The short version

| Question | Answer |
|---|---|
| Is it a working mouse? | **Yes, it has to be.** Nobody holds a fake, so it couldn't learn a baseline. Plan: a **donor mouse** (a cheap real one) keeps its own circuit board and its own cable or dongle to the laptop, so it behaves as a normal mouse. The YuDuino sits beside it, **electrically separate** (never join the two USB data lines). |
| Display? | **None.** The LED matrix inside stays dark (bring-up and debugging only; switch it off in the final firmware). See the trade-off in [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#what-we-lose-read-this). |
| PIN keys? | **None.** The mouse's own buttons are the only buttons. |
| How does the STM32 know about a click? | It **reads the real switch contact** of the mouse's left button (and wheel, if wanted) through a **read-only tap** (a high-value resistor or buffer into a GPIO). It never drives the line. Malware on the laptop can fake an OS click but cannot make a switch close. |
| Where is the UNO Q? | Flat in the base, next to the donor board. |
| What is on the palm? | The touch pad (grip gate), the moisture pads, and a vented pocket for the Thermo. |
| Where are the camera and YubiKey? | **Outside the mouse**, in a small **dock** (the Arduino USB-C hub). The YubiKey stays plugged in and is used **without a touch** (see [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#what-changes-in-the-crypto)). |
| How is the UNO Q powered, and how does it talk to the guardian? | A thin USB-C cable from the dock carries **power**. The UNO Q uses its **own Wi-Fi** to reach the guardian, so no data goes through the laptop. The donor mouse has its own, separate connection. |

## How the sensors map onto a mouse

| Signal | Part | Where in the mouse | Notes |
|---|---|---|---|
| **Click (the trigger, and click behaviour)** | Read-only tap on the donor switch lines | At the donor board's left-button switch (and wheel button) | STM32 timestamps each edge. The click is the trigger and also feeds the owner features (hold time, double-click gap). See "Tapping the switches" below |
| **Grip held** | DFRobot touch sensor (D2) | Under the **palm hump**, behind a thin wall (about 1 to 1.5 mm; capacitive sensors read through plastic) | Gates the trigger: a click only counts with the palm on the pad |
| **Sweat, contact, hand size** | DFRobot moisture sensor (A1) | Two exposed **copper tape pads** flush with the shell where the **palm heel** and the **thumb base** touch | A 1 kΩ resistor in each pad line (see ESD below). Contact resistance is also an owner feature |
| **Palm humidity and temperature** | Modulino Thermo | In a **vented pocket** under the hump (1 mm grille holes), **as far as possible from the UNO Q**, with an air gap | The board heats the shell, so absolute temperature drifts. The **humidity change** is the useful signal |
| **Tremor and movement style** | Modulino Movement | Screwed **rigidly to the shell**, not on the UNO Q | See "Tremor on a mouse" |
| **Face, scene, voice** | USB camera with mic | **Outside**, on the monitor or the dock | Not hidden; the mouse hides the *trusted device*, not the camera |

### Tapping the switches (the hardest bit of hardware)

A mouse switch is normally one side to ground and one side to the mouse chip's input. To let the STM32 see it **without disturbing the mouse**:

- Solder a thin wire to the switch's signal pad and bring it, through a **100 kΩ resistor** (or a small buffer, e.g. a Schmitt-trigger gate), to an STM32 pin set as input. The mouse chip keeps working exactly as before.
- **Check the voltage first** with a multimeter: the donor's logic level must not exceed what the UNO Q pin tolerates (it is a 3.3 V part). Use a level shifter or a resistor divider if not.
- **Read-only.** Never drive the line from the STM32.
- Test: open a mouse-test web page and click; the STM32's click log must match every click, and the cursor must work exactly as before.
- **Fallback if the tap is too fiddly:** use the Modulino Buttons (or a spare microswitch) physically under the same button cap, so one press closes both. A third fallback for a quick demo is to detect the click from the **accelerometer impulse** alone, which is weaker (see "Click quality" in [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)).

### Tremor on a mouse

A mouse sits on a desk and gets moved around, so the accelerometer sees the desk too. Two rules:

1. **Only read tremor while the mouse is still** (grip held, large slow motion small). Large slow motion means "someone moving the mouse", not tremor. Movement *style* (speed and smoothness while moving) is its own feature for the owner check.
2. **Filter to the tremor band** (about 4 to 12 Hz) and **ignore 100 ms around each click**, so the click itself isn't counted as a shake. This is a Wave 2 code change in `sketch.ino` (`shakeRms`); today it only removes the average.

## Layout

Top view, **front (fingers)** at the top. Typical mouse about **115 × 65 × 38 mm**; UNO Q board about **69 × 53 mm**. It is tight, so mock it up first.

```
        front (away from you)
   ┌───────────────────────────┐
   │   left btn  │  right btn   │  ← the donor mouse's own buttons, switch lines tapped read-only
   │        (scroll wheel)      │
   │   ┌───────────────────┐   │
   │   │ donor mouse board │   │  ← its own optical sensor and cable or dongle, untouched
   │   └───────────────────┘   │
   │   ┌───────────────────┐   │
   │   │     UNO Q (dark)  │   │  ← no window, no display
   │   └───────────────────┘   │
   │     ╭───────────────╮     │
   │     │  palm hump    │     │  ← touch pad (inside), moisture pads (flush)
   │     │  vent grille  │     │  ← Thermo pocket under it
   │     ╰───────────────╯     │
   └─────────────┬─────────────┘
                 │  thin USB-C cable (power) ──► dock: hub + camera + YubiKey
        back (towards you)
```

Stack, from the bottom: **base plate** with the UNO Q on four M2.5 standoffs (check the hole pattern) beside the donor board; **short Qwiic cables** (5 to 10 cm) to the Movement (screwed to a boss), the Thermo (far end), and nothing at the front because there are no PIN buttons any more; **top shell** (the donor's own, or printed) with the vent grille, the thin wall over the touch pad, the palm pad recesses and a cable notch. The **USB-C port** faces the rear. Keep the board's **Wi-Fi antenna** away from the palm (a hand detunes it) and test signal with a hand on it.

## Shell and 3D printing

- **Best:** reuse a donor mouse's shell, so it feels and sounds like a normal mouse. Use the printer for **a base plate, standoffs, the Thermo pocket and a palm-pad insert** that fit inside it.
- **Prototype:** a printed two-part shell (base and top). Print the top upside down so it needs no supports; PLA, 0.2 mm layers, about 3 perimeters. The size is large for a hobby bed, so start early and check the bed first.
- **Features to model:** standoffs; a boss for the Movement board; a 1.2 mm wall over the touch pad; recesses for copper tape; the vent grille; the cable notch with strain relief (a knot or zip tie inside); screw bosses.
- **Seal the screws** with a dot of paint so tampering shows.
- A printed shell has **no real buttons**, so use it only for fit and sensor tests. The final version needs the donor.

## Physical trade-offs

(The security trade-offs from having no screen and no PIN are in [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#what-we-lose-read-this).)

| # | Trade-off | Why it matters | What we do |
|---|---|---|---|
| 1 | **Hiding is not protection** | Anyone who opens it finds an ordinary UNO Q | The checks don't depend on secrecy. Sealed screws show tampering. Wave 4 locks the STM32 debug port ([weak spot 2](CRYPTO.md#remaining-weak-spots)) |
| 2 | **A look-alike mouse swapped in** | A fake could collect the user's habits or relay clicks | It can't produce a valid tag (no `K_MCU`), so approvals fail. The worst result is a refusal |
| 3 | **Tapping the donor's switches** | A bad tap could stop the mouse working or damage a pin | High-value resistor or buffer, voltage check, read-only; test with a mouse-test page |
| 4 | **The YubiKey is in the dock, not the mouse** | It isn't hidden, and (with no touch) it only proves possession | The dock sits behind the monitor; step-up asks for a touch ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)) |
| 5 | **The camera isn't hidden** | An attacker can see a camera and know someone judges them | The strongest signals (the owner check, physiology) don't depend on the camera |
| 6 | **Static from your hand (ESD)** | Bare pads on the palm can reset or damage the board | 1 kΩ series resistors on both pad lines; test after shuffling on carpet |
| 7 | **Heat in a closed shell** | The UNO Q warms the shell and the palm | Thermo far from the board; vent grille; rely on humidity change; baseline per device |
| 8 | **Wi-Fi is weaker inside a palm** | A failed guardian call fails closed, so a weak signal looks like an alarm | Check signal with a hand on; keep the antenna end clear |
| 9 | **Always-on collection** | The UNO Q needs power all day, and it collects data you didn't ask for each time | A thin power cable from the dock or a power bank; aggregates only; pause, view and delete controls ([BASELINE.md](BASELINE.md#privacy)) |
| 10 | **A stolen or borrowed mouse teaches the baseline wrong** | Someone else's hands become "normal" | Samples count only after the owner check and an accepted approval; duress samples are never added ([BASELINE.md](BASELINE.md#keeping-the-baseline-honest-poisoning)) |
| 11 | **The cable and dock are not secret** | A thick cable to a hub gives it away | Thin USB-C cable; hide the dock behind the monitor |
| 12 | **The donor mouse needs its own connection to the laptop** | Two cables or a dongle plus the power lead | Use a wireless donor mouse, so only the thin power lead is visible |

## Build order (before printing)

1. **Donor mouse first (30 min).** Open it, find the left-button switch, check the voltage, and solder the read-only tap. Confirm the mouse still works and the STM32 sees every click (mouse-test page).
2. **Cardboard mock-up of the rest (20 min).** Tape the UNO Q, Thermo and Movement inside or beside the donor shell. Hold it. Does it feel like a mouse? Is anything in the way of your fingers? Adjust.
3. **Run the invisible flow** from [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md) against the bench rig: click, and the approval goes through with no extra input.
4. **Measure and model** the base plate, standoffs and inserts; print the base first as a fit test.
5. **Assemble** with short Qwiic cables, copper pads, resistors and the strain relief. Re-run step 3 inside the shell.
6. **Mouse specifics:** the touch pad reads 1 only with the palm there; moisture rises on a damp palm; the tremor window ignores desk movement; Wi-Fi holds with a hand on; the mouse still works as a mouse for a day.

## What changes in the code

See [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#what-needs-to-change-in-the-code-not-done-yet). The repo is still the v2 code (PIN and matrix) until those changes are built.
