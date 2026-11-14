// MCU side (STM32 on the UNO Q).
// Reads all sensors, computes features on the MCU, and exposes them to the
// Linux side over Bridge. Python POLLS us with Bridge.call("get_features");
// we never call Python from inside a provide() handler (that can deadlock).
//
// The approval logic lives in yuseal_mcu.h and IS tested (python3 -m unittest test_yuseal).
// The glue below is UNVERIFIED on hardware — see the "VERIFY" comments and docs/PLAN.md.

#include <Arduino_RouterBridge.h>
#include <Modulino.h>
#include "yuseal_mcu.h"   // trusted approval core (docs/CRYPTO.md); tested on a laptop
#include "secrets.h"      // written by tools/provision.py, gitignored: K_MCU-derived PIN tags

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

// --- Button state. Presses go ONLY to the trusted core below, never to Linux. ---
bool   prevPressed[3] = {false, false, false};
yuseal::Mcu core;

// Scroll text on the 8x13 LED matrix. VERIFY against App Lab's LED matrix example
// (Arduino_LED_Matrix, scrolling text call). Until then the text goes to Serial so the
// logic can be tested.
void showText(const char* text) {
  Monitor.println(text);
}

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
  s += "\"state\":"      + String(int(core.state())) + ",";   // 0 idle, 1 entering PIN, 2 PIN ok, 3 locked
  s += "\"pin_count\":"  + String(core.pinCount());           // how many presses, never which ones
  s += "}";
  return s;
}

// ---------------- YuSeal approval calls (Linux -> STM32). All return Strings. ----------------
// Bridge handlers run on another thread than loop(), so they use provide_safe. VERIFY on the board that String arguments work; if not, pack them into one String and split here.

static bool fromHex(const String& h, uint8_t* out, size_t n) {
  if (h.length() != 2 * n) return false;
  for (size_t i = 0; i < n; i++) {
    char c[3] = {h[2 * i], h[2 * i + 1], 0};
    char* end;
    out[i] = (uint8_t)strtoul(c, &end, 16);
    if (*end) return false;
  }
  return true;
}
static String toHex(const uint8_t* b, size_t n) {
  static const char* d = "0123456789abcdef";
  String s;
  for (size_t i = 0; i < n; i++) { s += d[b[i] >> 4]; s += d[b[i] & 15]; }
  return s;
}

// Show `text` on the LED matrix and start waiting for the PIN. Returns "1" or "0".
String begin_approval(String text, String digestHex) {
  uint8_t digest[32];
  if (!fromHex(digestHex, digest, 32)) return "0";
  if (!core.begin(text.c_str(), digest, millis())) return "0";
  showText(text.c_str());
  return "1";
}

// "-" until a correct PIN (normal or duress, same answer), then the salt for the YubiKey.
String get_unlock_salt() {
  uint8_t salt[32];
  return core.unlockSalt(salt) ? toHex(salt, 32) : String("-");
}

// Linux passes Gemini's score as a whole number 0..100 (anything else = no usable verdict).
// Returns the 32-byte tag as hex, or "-". The matrix then shows OK in every case.
String seal_approval(String scoreStr, String vetoStr) {
  uint8_t tag[32];
  int score = scoreStr.toInt();
  if (!core.seal(score, vetoStr == "1", tag)) return "-";
  showText("OK");
  return toHex(tag, 32);
}

void setup() {
  Monitor.begin(115200);
  Bridge.begin();
  Modulino.begin();          // VERIFY: on UNO Q the Qwiic port may be Wire1; check Modulino docs/examples
  thermo.begin();
  movement.begin();
  buttons.begin();

  pinMode(TOUCH_PIN, INPUT);
  for (int i = 0; i < WIN; i++) mag[i] = 1.0;

  core.provision(YS_K_MCU, YS_PIN_TAG_NORMAL, YS_PIN_TAG_DURESS, YS_PIN_LEN);

  Bridge.provide_safe("get_features", get_features);
  Bridge.provide_safe("begin_approval", begin_approval);
  Bridge.provide_safe("get_unlock_salt", get_unlock_salt);
  Bridge.provide_safe("seal_approval", seal_approval);
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

  // Button edges go straight to the trusted core. A press only counts while the grip is held.
  // VERIFY: Buttons API (update()/isPressed(index) vs press callbacks) against the library docs.
  bool grip = digitalRead(TOUCH_PIN) == HIGH;
  if (buttons.update()) {
    for (int i = 0; i < 3; i++) {
      bool p = buttons.isPressed(i);
      if (p && !prevPressed[i]) core.buttonDown(char('A' + i), grip, millis());
      if (!p && prevPressed[i]) core.buttonUp(millis());
      prevPressed[i] = p;
    }
  }
  core.tick(millis());
}
