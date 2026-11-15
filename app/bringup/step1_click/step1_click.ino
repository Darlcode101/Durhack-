// Bring-up 1: the click tap. Wire a READ-ONLY tap (100 kOhm in series) from the donor mouse's
// left-button switch line to CLICK_PIN, and the palm-rest touch sensor to pin 2.
// PASS = the serial monitor prints "DOWN" when you click and "UP <ms held>" when you release,
// the mouse still clicks normally in the computer, and "grip=1" shows while your palm is on the mouse.
// If DOWN/UP never print or are inverted, check the switch line idles HIGH (it should), or swap the polarity below.
const int CLICK_PIN = 3;   // idles HIGH, LOW while the button is down
const int TOUCH_PIN = 2;
bool prev = false; unsigned long downAt = 0;
void setup() { Monitor.begin(115200); pinMode(CLICK_PIN, INPUT_PULLUP); pinMode(TOUCH_PIN, INPUT); Monitor.println("click tap test"); }
void loop() {
  bool c = digitalRead(CLICK_PIN) == LOW;
  if (c && !prev) { downAt = millis(); Monitor.print("DOWN grip="); Monitor.println(digitalRead(TOUCH_PIN)); }
  if (!c && prev) { Monitor.print("UP "); Monitor.println(millis() - downAt); }
  prev = c;
}
