// Bring-up 2: Qwiic chain (Thermo, Movement, Buttons).
// PASS = "found T M B", temperature ~room temp, accel Z ~1 g when flat, and pressing a button prints its letter.
// The I2C scan line lists every address that answered; empty means nothing is connected on that bus.
// UNO Q's Qwiic connector is Wire1 (as in Arduino's own examples). Set USE_WIRE1 to 0 only to compare.
#include <Arduino_Modulino.h>
#define USE_WIRE1 1
ModulinoThermo thermo; ModulinoMovement movement; ModulinoButtons buttons;
bool hasT, hasM, hasB;
unsigned long lastReport = 0;

void report() {
  Monitor.print("found ");
  Monitor.print(hasT ? "T " : "- "); Monitor.print(hasM ? "M " : "- "); Monitor.println(hasB ? "B" : "-");
  Monitor.print("i2c scan:");
  for (uint8_t a = 1; a < 127; a++) {
#if USE_WIRE1
    Wire1.beginTransmission(a); if (Wire1.endTransmission() == 0) { Monitor.print(" 0x"); Monitor.print(a, HEX); }
#else
    Wire.beginTransmission(a);  if (Wire.endTransmission() == 0)  { Monitor.print(" 0x"); Monitor.print(a, HEX); }
#endif
  }
  Monitor.println();
}

void setup() {
  Monitor.begin(115200);
#if USE_WIRE1
  Modulino.begin(Wire1);
#else
  Modulino.begin();
#endif
  hasT = thermo.begin(); hasM = movement.begin(); hasB = buttons.begin();
}

void loop() {
  if (millis() - lastReport > 3000) { lastReport = millis(); report(); }  // repeat: the monitor may attach late
  movement.update();   // ModulinoThermo has no update(); its getters read the sensor directly
  Monitor.print("T="); Monitor.print(thermo.getTemperature());
  Monitor.print(" H="); Monitor.print(thermo.getHumidity());
  Monitor.print(" z="); Monitor.println(movement.getZ());
  if (buttons.update()) for (int i = 0; i < 3; i++) if (buttons.isPressed(i)) Monitor.println(char('A' + i));
  delay(200);
}
