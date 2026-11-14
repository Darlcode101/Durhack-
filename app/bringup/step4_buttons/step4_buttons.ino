// Bring-up 4: the trusted core on its own (no Linux). Hold the touch grip, then press the PIN on the buttons.
// PASS = serial shows state 1 while typing, state 2 after the right PIN, 3 after 5 wrong PINs.
// Needs secrets.h from tools/provision.py copied next to this sketch (or in app/sketch).
#include <Modulino.h>
#include "../../sketch/yuseal_mcu.h"
#include "../../sketch/secrets.h"
ModulinoButtons buttons; yuseal::Mcu core; bool prev[3];
void setup() {
  Monitor.begin(115200); Modulino.begin(Wire1); buttons.begin(); pinMode(2, INPUT);
  core.provision(YS_K_MCU, YS_PIN_TAG_NORMAL, YS_PIN_TAG_DURESS, YS_PIN_LEN);
  uint8_t d[32] = {0}; core.begin("TEST", d, millis());
}
void loop() {
  bool grip = digitalRead(2) == HIGH;
  if (buttons.update()) for (int i = 0; i < 3; i++) {
    bool p = buttons.isPressed(i);
    if (p && !prev[i]) core.buttonDown('A' + i, grip, millis());
    if (!p && prev[i]) core.buttonUp(millis());
    prev[i] = p;
  }
  core.tick(millis());
  static unsigned long t; if (millis() - t > 500) { t = millis(); Monitor.print("state="); Monitor.print((int)core.state()); Monitor.print(" presses="); Monitor.println(core.pinCount()); }
}
