# Hardware

Back to the [README](../README.md).

## Wiring

The UNO Q, Modulinos and DFRobot sensors go inside the mouse. The hub, YubiKey and camera sit outside in a dock behind the monitor.

```
 wall -- Arduino 5 V 3 A adaptor --USB-C--> [hub PD in]
                                            [hub USB-A] camera
                                            [hub USB-A] YubiKey
                                            hub's own USB-C lead --> UNO Q

 UNO Q
   Qwiic --> Modulino Movement --> Modulino Thermo
   D3  <-- read-only tap on the mouse's left switch (100 kΩ in series)
   D2  <-- touch SIG        D7 --> touch VCC
   A1  <-- moisture AOUT    D8 --> moisture VCC
   GND --> touch GND, moisture GND (one GND pin each)
```

| Part | Connects to |
|---|---|
| Power adaptor | hub PD / power-in port |
| USB-C hub | the UNO Q's only USB-C port, using the hub's own lead |
| USB camera | hub USB-A port 1 |
| YubiKey 5 NFC | hub USB-A port 2 |
| Modulino Movement, Thermo | Qwiic chain (the port is `Wire1` on the UNO Q) |
| DFRobot touch sensor | VCC to D7, GND, SIG to D2 |
| DFRobot moisture sensor | VCC to D8, GND, AOUT to A1 |
| Mouse left switch | read-only tap to D3 |

A few things we learned the hard way:

- The UNO Q's pins are 3.3 V, so power the DFRobot sensors at 3.3 V. We power each one from its own pin (D7, D8) that the sketch drives high, because sharing the single 3V3 pin left both of them unpowered on our first build.
- `get_features` reports `touch_wire`. `floating` means nothing is driving D2 (no power or a loose wire). `driven low` means the sensor is powered and untouched.
- The Modulinos need Arduino_Modulino 0.10.0. Newer Thermos use a GXHT30C at 0x45 that 0.7.0 can't find.
- The hub's own USB-C lead has to go into the UNO Q (not the PD input) for the board to act as USB host for the YubiKey and camera.
- Keep the camera and YubiKey on separate hub ports and don't plug anything else in. The hub shares one 3 A supply.

## Building the mouse

We use a cheap real mouse as a donor. It keeps its own circuit board and its own connection to the laptop, so it works exactly as before, and the UNO Q sits next to it and is electrically separate. Never join the two USB data lines.

1. Open the donor mouse, find the left-button switch, and check its logic level with a multimeter. It must not go over 3.3 V.
2. Solder a thin wire from the switch's signal pad through a 100 kΩ resistor to D3. The STM32 only reads it.
3. Put the touch sensor under the palm hump behind a thin wall (about 1 to 1.5 mm, it reads through plastic).
4. Make two moisture pads from copper tape where the palm heel and thumb base rest, each with a 1 kΩ resistor in line to protect against static.
5. Put the Thermo in a vented pocket as far from the UNO Q as you can, since the board warms the shell. Screw the Movement rigidly to the shell.
6. Use short Qwiic cables (5 to 10 cm) and tape or hot glue every joint.
7. Run a thin USB-C power lead out the back to the dock. A wireless donor mouse means that's the only visible cable.

Test it on a mouse-test web page: every click should show up on the STM32 and the cursor should behave normally. Then check Wi-Fi still holds with a hand on the mouse.

## Bring-up sketches

Upload these from `app/bringup/` one at a time before the full sketch. The comment at the top of each says what a pass looks like.

| Sketch | Checks |
|---|---|
| `step1_click` | the click tap and the grip sensor. Prints DOWN/UP with the hold time and `grip=1` with your palm on |
| `step2_qwiic` | Thermo and Movement. If nothing is found, flip `USE_WIRE1` |
| `step3_dfrobot` | touch reads 1 only while touched, moisture rises with a damp finger |
| `step4_core` | the STM32 core on its own (needs `secrets.h` from `tools/provision.py`). A click with a palm arms and seals once, a click without one is refused |

No donor mouse yet? Uncomment `#define CLICK_FROM_MODULINO_BUTTON` in `sketch.ino` and use a Modulino Buttons button A as the click on the bench.
