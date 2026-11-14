// Bring-up 1: LED matrix text. PASS = "HELLO" scrolls across the 8x13 matrix and the serial monitor prints it.
#include <ArduinoGraphics.h>
#include <Arduino_LED_Matrix.h>
ArduinoLED matrix;
int x = 13;
void setup() { Monitor.begin(115200); matrix.begin(); Monitor.println("matrix test"); }
void loop() {
  matrix.beginDraw(); matrix.clear(); matrix.stroke(0xFFFFFFFF);
  matrix.textFont(Font_5x7); matrix.beginText(x, 1, 0xFFFFFF); matrix.print("HELLO"); matrix.endText(); matrix.endDraw();
  if (--x < -30) x = 13;
  delay(120);
}
