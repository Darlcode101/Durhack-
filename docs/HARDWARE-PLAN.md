# YuDuino hardware plan: getting the basics running

A step-by-step bring-up for the kit we actually have. Add one part at a time and don't move on until its test passes, so when something breaks you know which part caused it.

Pin choices match the existing code in [`app/sketch/sketch.ino`](../app/sketch/sketch.ino). Product background is in [YuDuino-Overview.md](YuDuino-Overview.md); team schedule in [PLAN.md](PLAN.md).

## What plugs into what

The board, the Modulinos and the DFRobot sensors now sit **inside a working mouse** (see [MOUSE-DESIGN.md](MOUSE-DESIGN.md)). The hub, camera and YubiKey are the **dock** outside it.

```
 Wall ── Arduino power adaptor (5 V 3 A)
            │ USB-C to USB-C cable
            ▼
     ┌─ Arduino USB-C hub ───────────────────────────┐
     │  [PD in]   [USB-A] camera+mic   [USB-A] YubiKey* │
     └───────────────┬────────────────────────────────┘
                     │ hub's own USB-C lead
                     ▼
              ┌──────────────── Arduino UNO Q ────────────────┐
              │  LED matrix 8×13 (built in) = trusted display   │
              │                                                 │
              │  Qwiic ──► Modulino Buttons ──► Movement ──► Thermo
              │                                                 │
              │  D7  ──► touch VCC          GND ─┬─ touch GND    │
              │  D8  ──► moisture VCC            └─ moisture GND │
              │  D2  ◄── touch SIG                              │
              │  A1  ◄── moisture AOUT                          │
              └─────────────────────────────────────────────────┘

 * Milestone 1: the YubiKey goes in the LAPTOP (WebAuthn through an SSH tunnel).
   Moving it to the hub is a stretch goal.
```

## Pin and port assignments

| Part | Connector on part | Goes to on UNO Q | Wire |
|---|---|---|---|
| Power adaptor | USB-C | Hub **PD / power-in** port | USB-C to C cable |
| USB-C hub | USB-C plug | UNO Q USB-C (its only one) | Built-in lead |
| USB camera + mic | USB-A | Hub USB-A port 1 | Built-in lead |
| YubiKey 5 NFC | USB-A | Laptop for milestone 1; hub USB-A port 2 later | — |
| Modulino Buttons | Qwiic | UNO Q **Qwiic** connector | Qwiic cable |
| Modulino Movement | Qwiic | Buttons' second Qwiic socket | Qwiic cable |
| Modulino Thermo | Qwiic | Movement's second Qwiic socket | Qwiic cable |
| DFRobot touch v2 | VCC / GND / SIG | **D7** (power pin) / GND / **D2** | 3 male-to-male jumpers |
| DFRobot moisture v2 | VCC / GND / AOUT | **D8** (power pin) / GND / **A1** | 3 male-to-male jumpers |

**Rules**
- **3.3 V only** for the DFRobot sensors. The UNO Q's pins are 3.3 V; powering a sensor from 5 V can push its output above what the pins tolerate.
- **Power each DFRobot sensor from its own pin (D7, D8), not the 3V3 pin.** The board has only one 3V3 pin, and a shared joint there left both sensors unpowered on the first build (D2 read "floating"). The sketch drives D7 and D8 high at 3.3 V; each sensor draws only a few mA. Use the two GND pins, one per sensor.
- **Check it:** `get_features` reports `touch_wire`. `floating` means nothing drives D2 (no power or a loose signal wire); `driven low` means the sensor is powered and untouched.
- Modulino chain order doesn't matter electrically; Buttons first keeps the cable to the user's thumb short.
- Default I2C addresses, for checking a scan: Thermo `0x44`, Movement `0x6A`, Buttons `0x7C`. Verify on the board; they can differ.
- Keep the camera and YubiKey on separate hub ports, and don't plug in anything else: the hub shares one 3 A supply.

## Bring-up order

Each step lists what to do and the test that must pass before moving on. Times are rough.

### Step 0: board, power and network (30 min)
1. Laptop: install **Arduino App Lab**. Plug the UNO Q straight into the laptop first (no hub) and let App Lab update it.
2. Connect the board to Wi-Fi. Use a **phone hotspot**: venue Wi-Fi with a sign-in page won't work on the board.
3. Now move to the real setup: power adaptor → hub power-in, hub → UNO Q.
4. Check you can reach it: `ssh arduino@<board-name>.local`.

**Test:** App Lab sees the board while it's powered through the hub, and SSH works. If it resets randomly, the power supply is too weak; use the Arduino adaptor, not a laptop port.

### Step 1: LED matrix, our display (20 min)
1. Run App Lab's LED matrix example.
2. Change it to scroll `YUDUINO`, then `PAY 10 GBP ...A1F3?`.

**Test:** the text is readable from arm's length. (VERIFY: the exact LED matrix library and text-scrolling call for the UNO Q; follow App Lab's bundled example.)

### Step 2: the Qwiic chain, one Modulino at a time (45 min)
1. Install the **`Arduino_Modulino`** library.
2. Plug in **Thermo only**. Run its example; print temperature and humidity.
3. Add **Movement**. Print X, Y, Z; shake it and watch the numbers jump.
4. Add **Buttons**. Print which button is pressed.

**Test:** all three report at once. Breathe on the Thermo and the humidity rises. If nothing is found, check `Modulino.begin()` versus `Wire1` (listed in PLAN.md's verify list) and run an I2C scan.

### Step 3: the DFRobot sensors (30 min)
1. Power **off**. Wire the touch sensor: VCC → **D7**, GND → GND, SIG → D2.
2. Print `digitalRead(2)` and touch the pad.
3. Power off. Wire the moisture sensor: VCC → **D8**, GND → GND, AOUT → A1.
4. Print `analogRead(A1)`. Hold it dry, then press a damp finger on it.

**Test:** touch reads 1 when touched and 0 when not. Moisture changes clearly between a dry and a damp finger. Note both values: they're the first baseline.

### Step 4: sensors to Linux over Bridge (45 min)
1. Upload the repo's [`sketch.ino`](../app/sketch/sketch.ino) in App Lab.
2. Run [`main.py`](../app/python/main.py) on the Linux side.

**Test:** Python prints a JSON line with real `temp_c`, `humidity`, `shake_rms`, `touch`, `moisture`, `state` and `pin_count` values. Holding the grip and pressing buttons A, B, C changes `pin_count` (Linux sees how many presses, never which). The PIN itself stays on the STM32; see [BUILD-FLOW.md](BUILD-FLOW.md).

### Step 5: camera and microphone (30 min)
1. Plug the camera into hub USB-A port 1.
2. Over SSH: `lsusb` (camera listed), `v4l2-ctl --list-devices` (a `/dev/video` device), `arecord -l` (a capture device for the mic).
3. Run `camera.py` to grab one frame and count faces.

**Test:** one face counts 1, two people count 2. A 3-second `arecord` clip plays back with your voice.

### Step 6: YubiKey (45 min)
1. **Basic route (do this first):** keep the YubiKey in the laptop. Open the dashboard through `ssh -L 8000:localhost:8000 arduino@<board>.local`, then visit `http://localhost:8000` and register the key with WebAuthn.
2. **Stretch route:** plug the YubiKey into hub port 2. `lsusb` should list Yubico. Then try `python-fido2` on the UNO Q. App Lab's container may block USB access, in which case run that Python over SSH.

**Test:** register once, then log in with a tap.

## Milestone 1: "the basics"

One end-to-end approval, no AI yet:

1. Laptop script sends a request: *pay 10 GBP to ...A1F3*.
2. LED matrix scrolls `PAY 10 GBP ...A1F3?`.
3. User holds the grip (touch = 1) and enters the PIN on the Buttons (short press = `A`, `B`, `C`; press held 0.8 s or more = `a`, `b`, `c`; example `ABCABCAB`).
4. User taps the YubiKey.
5. LED matrix shows `OK`. A wrong PIN or no tap shows `NO`.
6. The terminal prints the averaged sensor readings and face count.
7. Entering the **duress PIN** (same presses, last one held long: `ABCABCAb`) also shows `OK`, but the guardian logs `hold_and_alert` and nothing would be paid.

When all seven work, the hardware is done. Everything after is software: baseline enrolment and rules (milestone 2), Gemini and the silent alert (milestone 3), then the grip enclosure and demo script (milestone 4).

## Building the mouse

The device lives inside a **normal-working mouse** with **no screen and no PIN** (see [MOUSE-DESIGN.md](MOUSE-DESIGN.md) for the layout and build order, and [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md) for the flow). Steps 1 to 6 above still apply on the desk; the Buttons and the LED matrix are bring-up tools only, and are not in the final mouse. Once Milestone 1 works on the desk:
- **Donor mouse first.** Find the left-button switch, check its voltage, and solder a **read-only tap** (100 kΩ or a buffer) to an STM32 pin. The mouse must still work exactly as before.
- Touch pad under the palm hump (thin wall); moisture pads of copper tape flush at the palm heel and thumb base, each with a 1 kΩ resistor in line.
- Thermo in a vented pocket as far from the UNO Q as possible. Movement screwed rigidly to the shell.
- **No window, no keys.** The LED matrix stays dark; switch it off in the final firmware.
- Short Qwiic cables (5 to 10 cm) and tape or hot glue on every joint.
- The **camera and YubiKey stay outside** in the dock (the USB-C hub); the mouse's thin USB-C cable (power only) plugs into it. The UNO Q uses its own Wi-Fi.

## Shopping gaps

Ask Arduino for these if they're available:
- **Short Qwiic cables** (5 to 10 cm) for the inside of the mouse, and a few spare 1 kΩ resistors, copper tape, M2.5 standoffs and screws.
- **A cheap real mouse** (preferably wireless) as the donor, plus fine solder wire and 100 kΩ resistors for the switch tap.
- **Any small HDMI screen** for a better trusted display, if the hub has an HDMI port. The LED matrix stays as the fallback.
- **A USB-A to USB-C adapter**, if the hub has only one USB-A port.
