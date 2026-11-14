# YuDuino hardware plan: getting the basics running

A step-by-step bring-up for the kit we actually have. Add one part at a time and don't move on until its test passes, so when something breaks you know which part caused it.

Pin choices match the existing code in [`app/sketch/sketch.ino`](../app/sketch/sketch.ino). Product background is in [YuDuino-Overview.md](YuDuino-Overview.md); team schedule in [PLAN.md](PLAN.md).

## What plugs into what

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
              │  3.3V ─┬─ touch VCC        GND ─┬─ touch GND    │
              │        └─ moisture VCC          └─ moisture GND │
              │  D2  ◄── touch SIG                              │
              │  A0  ◄── moisture AOUT                          │
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
| DFRobot touch v2 | VCC / GND / SIG | **3.3V** / GND / **D2** | 3 male-to-male jumpers |
| DFRobot moisture v2 | VCC / GND / AOUT | **3.3V** / GND / **A0** | 3 male-to-male jumpers |

**Rules**
- **3.3 V only** for the DFRobot sensors. The UNO Q's pins are 3.3 V; powering a sensor from 5 V can push its output above what the pins tolerate.
- Both sensors share 3.3V and GND. The headers have only a couple of each, so either use both GND pins, or twist two jumpers into one with a crocodile clip (it counts for hackiest hack).
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
1. Power **off**. Wire the touch sensor: VCC → 3.3V, GND → GND, SIG → D2.
2. Print `digitalRead(2)` and touch the pad.
3. Power off. Wire the moisture sensor: VCC → 3.3V, GND → GND, AOUT → A0.
4. Print `analogRead(A0)`. Hold it dry, then press a damp finger on it.

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

## Building the grip

Once milestone 1 works, move the sensors off the desk into one handheld object:
- Touch pad where the palm rests; moisture probe where the fingers wrap.
- Thermo near the palm, but not touching skin (it measures the air humidity there).
- Movement taped flat inside, so it feels the hand's tremor.
- Buttons under the thumb.
- Use long Qwiic cables and tape every joint; a loose jumper mid-demo looks like duress.

## Shopping gaps

Ask Arduino for these if they're available:
- **Long Qwiic cables** (20 cm+) for the grip.
- **Any small HDMI screen** for a better trusted display, if the hub has an HDMI port. The LED matrix stays as the fallback.
- **A USB-A to USB-C adapter**, if the hub has only one USB-A port.
