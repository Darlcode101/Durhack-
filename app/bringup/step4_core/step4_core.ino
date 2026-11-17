// Bring-up 4: the trusted core on its own (no Linux). Needs secrets.h from tools/provision.py (in app/sketch).
// Click the mouse with your palm on it. PASS = after each click within 1.5 s, "armed" prints once,
// then "sealed <tag first 4 bytes>" (the tag changes every time because the click age and sensors differ).
// A click with no palm on the grip, or a second arm for the same click, prints "refused".
// Set CLICK_PIN/TOUCH_PIN to match step 1. No donor mouse (or no access to the pins)? Uncomment
// CLICK_FROM_MODULINO_BUTTON to use a Modulino button as the click (CLICK_BUTTON: 0 = A, 1 = B, 2 = C).
//
// App Lab builds from its own copy of the sketch folder, so relative includes like
// "../../sketch/yuseal_mcu.h" are not found. Copy app/sketch/yuseal_mcu.h and app/sketch/secrets.h
// into this sketch's folder next to the .ino before building (secrets.h is gitignored everywhere).
#include "yuseal_mcu.h"
#include "secrets.h"
// #define CLICK_FROM_MODULINO_BUTTON
#define CLICK_BUTTON 2
#ifdef CLICK_FROM_MODULINO_BUTTON
#include <Arduino_Modulino.h>
ModulinoButtons buttons;
#endif
const int CLICK_PIN = 3, TOUCH_PIN = 2;
const int TOUCH_PWR_PIN = 7;   // the touch sensor is powered from D7 (docs/HARDWARE.md)
yuseal::Mcu core; bool prev = false;
bool gripAtDown = false;       // debug: the grip reading the core was given at the press
void setup() {
  Monitor.begin(115200); pinMode(TOUCH_PIN, INPUT);
  pinMode(TOUCH_PWR_PIN, OUTPUT); digitalWrite(TOUCH_PWR_PIN, HIGH);
  delay(300);                  // the touch chip calibrates for ~0.25 s after power-up
#ifdef CLICK_FROM_MODULINO_BUTTON
  Modulino.begin(Wire1); buttons.begin();
#else
  pinMode(CLICK_PIN, INPUT_PULLUP);
#endif
  core.provision(YS_K_MCU);
}
void loop() {
  bool grip = digitalRead(TOUCH_PIN) == HIGH;
#ifdef CLICK_FROM_MODULINO_BUTTON
  bool c = buttons.update() ? (bool)buttons.isPressed(CLICK_BUTTON) : prev;
#else
  bool c = digitalRead(CLICK_PIN) == LOW;
#endif
  if (c && !prev) { gripAtDown = grip; core.clickDown(millis(), grip); }
  if (!c && prev) {
    core.clickUp(millis());
    // Debug: what the core saw for this click, so a "refused" can be explained.
    Monitor.print("click: grip_at_press="); Monitor.print(gripAtDown ? 1 : 0);
    Monitor.print(" grip_now="); Monitor.print(grip ? 1 : 0);
    Monitor.print(" hold_ms="); Monitor.println(core.lastHoldMs());
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
