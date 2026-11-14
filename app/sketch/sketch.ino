// MCU side (STM32 on the UNO Q).
// Reads all sensors, computes features on the MCU, and exposes them to the
// Linux side over Bridge. Python POLLS us with Bridge.call("get_features");
// we never call Python from inside a provide() handler (that can deadlock).
//
// UNVERIFIED on hardware — see the "VERIFY" comments and docs/PLAN.md.

#include <Arduino_RouterBridge.h>
#include <Modulino.h>

// --- Qwiic chain: Thermo + Movement + Buttons all on the one Qwiic port ---
ModulinoThermo   thermo;
ModulinoMovement movement;
ModulinoButtons  buttons;

// --- Analog / digital sensors (power them from 3.3V, not 5V) ---
const int TOUCH_PIN    = 2;   // TTP223-style capacitive touch, digital out
const int MOISTURE_PIN = A0;  // resistive probe used as a crude sweat/contact proxy

// --- Shake (tremor) estimate: RMS of accel magnitude around its mean ---
const int   WIN = 64;          // ~0.64 s at 100 Hz
float       mag[WIN];
int         magIdx = 0;
unsigned long lastSample = 0;

// --- Button PIN entry: record press sequence as a string like "ABCA" ---
String pinBuffer = "";
bool   prevPressed[3] = {false, false, false};

float shakeRms() {
  float mean = 0;
  for (int i = 0; i < WIN; i++) mean += mag[i];
  mean /= WIN;
  float acc = 0;
  for (int i = 0; i < WIN; i++) { float d = mag[i] - mean; acc += d * d; }
  return sqrt(acc / WIN);
}

// Returned to Python as a JSON string so we don't depend on Bridge's type mapping.
String get_features() {
  String s = "{";
  s += "\"temp_c\":"     + String(thermo.getTemperature(), 2) + ",";
  s += "\"humidity\":"   + String(thermo.getHumidity(), 2) + ",";
  s += "\"shake_rms\":"  + String(shakeRms(), 4) + ",";
  s += "\"touch\":"      + String(digitalRead(TOUCH_PIN)) + ",";
  s += "\"moisture\":"   + String(analogRead(MOISTURE_PIN)) + ",";
  s += "\"pin_entry\":\"" + pinBuffer + "\"";
  s += "}";
  return s;
}

String clear_pin() {
  pinBuffer = "";
  return "ok";
}

void setup() {
  Bridge.begin();
  Modulino.begin();          // VERIFY: on UNO Q the Qwiic port may be Wire1; check Modulino docs/examples
  thermo.begin();
  movement.begin();
  buttons.begin();

  pinMode(TOUCH_PIN, INPUT);
  for (int i = 0; i < WIN; i++) mag[i] = 1.0;

  Bridge.provide("get_features", get_features);
  Bridge.provide("clear_pin", clear_pin);
}

void loop() {
  // 100 Hz accel sampling for the shake window
  if (millis() - lastSample >= 10) {
    lastSample = millis();
    movement.update();
    float x = movement.getX(), y = movement.getY(), z = movement.getZ();  // VERIFY getX/getY exist (seen in samples only)
    mag[magIdx] = sqrt(x * x + y * y + z * z);
    magIdx = (magIdx + 1) % WIN;
  }

  // Button edges -> PIN characters A/B/C
  // VERIFY: Buttons API (update()/isPressed(index) vs press callbacks) against the library docs.
  if (buttons.update()) {
    for (int i = 0; i < 3; i++) {
      bool p = buttons.isPressed(i);
      if (p && !prevPressed[i] && pinBuffer.length() < 12) pinBuffer += char('A' + i);
      prevPressed[i] = p;
    }
  }
}
