// MCU side (STM32 on the UNO Q).
// Reads all sensors, computes features on the MCU, and exposes them to the
// Linux side over Bridge. Python POLLS us with Bridge.call("get_features").
//
// Bridge handlers run on a separate thread from loop(), so ALL I2C reads
// (Thermo, Movement, Buttons) happen in loop(); handlers only read cached
// values from fixed-size buffers (no String/heap sharing between threads).
//
// Modulino calls checked against Arduino_Modulino 0.7.0 and the UNO Q example apps.

#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>

// --- Qwiic chain: Thermo + Movement + Buttons all on the one Qwiic port ---
ModulinoThermo   thermo;
ModulinoMovement movement;
ModulinoButtons  buttons;

// --- Analog / digital sensors (power them from 3.3V, not 5V) ---
const int TOUCH_PIN    = 2;   // TTP223-style capacitive touch, digital out
const int MOISTURE_PIN = A0;  // resistive probe used as a crude sweat/contact proxy

// --- Which Modulinos answered at startup ---
bool hasThermo = false, hasMovement = false, hasButtons = false;

// --- Cached readings (written in loop, read by the Bridge thread) ---
volatile float tempC = NAN, humidity = NAN, shake = 0;
volatile int touchVal = 0, moistureVal = 0;

// --- Shake (tremor) estimate: RMS of accel magnitude around its mean ---
const int   WIN = 64;          // ~0.64 s at 100 Hz
float       mag[WIN];
int         magIdx = 0;
unsigned long lastSample = 0, lastThermo = 0;

// --- Button PIN entry: press sequence like "ABCA" in a fixed buffer ---
const int PIN_MAX = 12;
char pinBuf[PIN_MAX + 1] = {0};
volatile int pinLen = 0;
volatile bool clearRequested = false;
bool prevPressed[3] = {false, false, false};

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
  char pin[PIN_MAX + 1];
  int n = pinLen;
  memcpy(pin, pinBuf, n);
  pin[n] = 0;
  String s = "{";
  s += "\"temp_c\":"     + String(tempC, 2) + ",";
  s += "\"humidity\":"   + String(humidity, 2) + ",";
  s += "\"shake_rms\":"  + String(shake, 4) + ",";
  s += "\"touch\":"      + String(touchVal) + ",";
  s += "\"moisture\":"   + String(moistureVal) + ",";
  s += "\"pin_entry\":\"" + String(pin) + "\",";
  s += "\"modulinos\":\"" + String(hasThermo ? "T" : "-") + (hasMovement ? "M" : "-") + (hasButtons ? "B" : "-") + "\"";
  s += "}";
  return s;
}

String clear_pin() {
  clearRequested = true;  // loop() does the actual clearing
  return "ok";
}

void setup() {
  Bridge.begin();
  Modulino.begin(Wire1);     // UNO Q's Qwiic connector is on Wire1 (as in Arduino's examples)
  hasThermo   = thermo.begin();
  hasMovement = movement.begin();
  hasButtons  = buttons.begin();

  pinMode(TOUCH_PIN, INPUT);
  for (int i = 0; i < WIN; i++) mag[i] = 1.0;

  Bridge.provide("get_features", get_features);
  Bridge.provide("clear_pin", clear_pin);
}

void loop() {
  unsigned long now = millis();

  // 100 Hz accel sampling for the shake window
  if (hasMovement && now - lastSample >= 10) {
    lastSample = now;
    if (movement.update()) {
      float x = movement.getX(), y = movement.getY(), z = movement.getZ();
      mag[magIdx] = sqrt(x * x + y * y + z * z);
      magIdx = (magIdx + 1) % WIN;
      shake = shakeRms();
    }
  }

  // Thermo + analog/digital every 200 ms
  if (now - lastThermo >= 200) {
    lastThermo = now;
    if (hasThermo) {
      tempC = thermo.getTemperature();
      humidity = thermo.getHumidity();
    }
    touchVal = digitalRead(TOUCH_PIN);
    moistureVal = analogRead(MOISTURE_PIN);
  }

  if (clearRequested) {
    pinLen = 0;
    pinBuf[0] = 0;
    clearRequested = false;
  }

  // Button edges -> PIN characters A/B/C
  if (hasButtons && buttons.update()) {
    for (int i = 0; i < 3; i++) {
      bool p = buttons.isPressed(i);
      if (p && !prevPressed[i] && pinLen < PIN_MAX) {
        pinBuf[pinLen] = char('A' + i);
        pinLen = pinLen + 1;
      }
      prevPressed[i] = p;
    }
  }
}
