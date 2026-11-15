// Bring-up 4: the trusted core on its own (no Linux). Needs secrets.h from tools/provision.py (in app/sketch).
// Click the mouse with your palm on it. PASS = after each click within 1.5 s, "armed" prints once,
// then "sealed <tag first 4 bytes>" (the tag changes every time because the click age and sensors differ).
// A click with no palm on the grip, or a second arm for the same click, prints "refused".
// Set CLICK_PIN/TOUCH_PIN to match step 1.
#include "../../sketch/yuseal_mcu.h"
#include "../../sketch/secrets.h"
const int CLICK_PIN = 3, TOUCH_PIN = 2;
yuseal::Mcu core; bool prev = false;
void setup() {
  Monitor.begin(115200); pinMode(CLICK_PIN, INPUT_PULLUP); pinMode(TOUCH_PIN, INPUT);
  core.provision(YS_K_MCU);
}
void loop() {
  bool grip = digitalRead(TOUCH_PIN) == HIGH, c = digitalRead(CLICK_PIN) == LOW;
  if (c && !prev) core.clickDown(millis(), grip);
  if (!c && prev) {
    core.clickUp(millis());
    static unsigned long fake = 0; fake++;
    uint8_t d[32] = {0}; d[0] = fake; int32_t f[yuseal::N_FEATURES] = {0}; f[5] = core.lastHoldMs();
    if (core.arm(d, millis(), f)) {
      Monitor.println("armed");
      uint8_t tag[32]; core.seal(10, false, tag);
      Monitor.print("sealed "); for (int i = 0; i < 4; i++) Monitor.print(tag[i], HEX); Monitor.println();
    } else Monitor.println("refused");
  }
  prev = c; core.tick(millis());
}
