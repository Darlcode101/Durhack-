// Bring-up 2: Qwiic chain (Thermo, Movement, Buttons).
// PASS = temperature ~room temp, accel Z ~1 g when flat, and pressing a button prints its letter.
// If Modulino.begin() finds nothing, change USE_WIRE1 to 0 (or 1) and re-upload. That answers the Wire/Wire1 question.
#include <Modulino.h>
#define USE_WIRE1 1
ModulinoThermo thermo; ModulinoMovement movement; ModulinoButtons buttons;
void setup() {
  Monitor.begin(115200);
#if USE_WIRE1
  Modulino.begin(Wire1);
#else
  Modulino.begin();
#endif
  thermo.begin(); movement.begin(); buttons.begin();
}
void loop() {
  thermo.update(); movement.update();
  Monitor.print("T="); Monitor.print(thermo.getTemperature());
  Monitor.print(" H="); Monitor.print(thermo.getHumidity());
  Monitor.print(" z="); Monitor.println(movement.getZ());
  if (buttons.update()) for (int i = 0; i < 3; i++) if (buttons.isPressed(i)) Monitor.println(char('A' + i));
  delay(200);
}
