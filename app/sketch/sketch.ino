// MCU side (STM32 on the UNO Q), zero-input mouse mode.
// The device sits inside an ordinary mouse. Nobody presses anything on it: the person's normal
// click on "process transaction" reaches us through a READ-ONLY tap on the left-button switch
// line (a 100 kOhm resistor or a buffer, so the mouse itself is never affected).
// Python POLLS us with Bridge.call(...); we never call Python from inside a provide() handler.
//
// The approval logic lives in yuseal_mcu.h and IS tested (python3 -m unittest test_yuseal).
// Everything in this file is board glue and is UNVERIFIED on hardware until the bring-up
// sketches in app/bringup have been run on the board.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include "yuseal_mcu.h"   // trusted approval core (docs/CRYPTO.md); tested on a laptop
#include "baseline_mcu.h"  // rolling per-hour baseline of the body sensors; tested on a laptop
#include "secrets.h"      // written by tools/provision.py, gitignored: YS_K_MCU

// --- Qwiic chain: Thermo + Movement (+ Buttons only for the bench click, see below) ---
ModulinoThermo   thermo;
ModulinoMovement movement;
ModulinoButtons  buttons;

// --- The physical click. Real build: a read-only tap on the donor mouse's left-button line;
// it idles HIGH (pull-up) and goes LOW while the button is down. Bench build with no donor
// mouse: uncomment CLICK_FROM_MODULINO_BUTTON to use a Modulino button as the click instead
// (CLICK_BUTTON picks which: 0 = A, 1 = B, 2 = C).
const int CLICK_PIN = 3;
// #define CLICK_FROM_MODULINO_BUTTON
#define CLICK_BUTTON 2

// --- Analog / digital sensors (power them from 3.3V, not 5V) ---
const int TOUCH_PIN    = 2;   // TTP223-style capacitive touch on the palm rest: "a hand is on the mouse"
const int MOISTURE_PIN = A1;  // resistive probe used as a crude sweat/contact proxy

yuseal::Mcu core;
yuseal::HourBaseline baseline;   // RAM here; Linux keeps an AES-256-GCM encrypted copy and restores it at boot
bool prevClick = false;

// --- Rolling sensor window (about 0.64 s at 100 Hz). Becomes the ten integer features at arm time. ---
const int   WIN = 64;
float       mag[WIN];
int         magIdx = 0;
unsigned long lastSample = 0;
float         magPrev = 1.0, moveAbs = 0;   // moveAbs: moving average of |change in accel magnitude|
uint8_t       stillWin[WIN], gripWin[WIN];  // 1 per sample: "still", "palm on the grip"
float         impulsePeak = 0;              // biggest jolt in the 60 ms after a click began
unsigned long impulseUntil = 0;

// Hex addresses that answered on Wire1 at boot, reported in get_features to debug the Qwiic chain.
char i2cFound[96] = "";
void scanI2C() {
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire1.beginTransmission(addr);
    if (Wire1.endTransmission() == 0 && strlen(i2cFound) < sizeof(i2cFound) - 6) {
      char buf[6];
      snprintf(buf, sizeof(buf), "%02X ", addr);
      strcat(i2cFound, buf);
    }
  }
}

float shakeRms() {
  float mean = 0;
  for (int i = 0; i < WIN; i++) mean += mag[i];
  mean /= WIN;
  float acc = 0;
  for (int i = 0; i < WIN; i++) { float d = mag[i] - mean; acc += d * d; }
  return sqrt(acc / WIN);
}

static int permille(const uint8_t* w) {
  int n = 0;
  for (int i = 0; i < WIN; i++) n += w[i];
  return n * 1000 / WIN;
}

// The ten features, in the order of yuseal.py FEATURE_NAMES. Scaled integers, so the C++
// and Python sides hash the same bytes.
void computeFeatures(int32_t f[yuseal::N_FEATURES]) {
  f[0] = permille(gripWin);                                   // grip_permille
  f[1] = int32_t(shakeRms() * 1000);                          // tremor_milli
  f[2] = int32_t(thermo.getHumidity() * 100);                 // humidity_centi
  f[3] = int32_t(thermo.getTemperature() * 100);              // temp_centi
  f[4] = analogRead(MOISTURE_PIN);                            // moisture_raw
  f[5] = core.lastHoldMs();                                   // click_hold_ms
  f[6] = permille(stillWin);                                  // still_permille
  f[7] = int32_t(moveAbs * 1000);                             // move_speed_milli
  f[8] = int32_t(impulsePeak * 1000);                         // click_impulse_milli
  f[9] = WIN;                                                 // n_samples
}

// Returned to Python as a JSON string so we don't depend on Bridge's type mapping.
// Used by Linux for the model window and the onboard veto. Never contains the status.
String get_features() {
  String s = "{";
  s += "\"temp_c\":"     + String(thermo.getTemperature(), 2) + ",";
  s += "\"humidity\":"   + String(thermo.getHumidity(), 2) + ",";
  s += "\"shake_rms\":"  + String(shakeRms(), 4) + ",";
  s += "\"grip\":"       + String(digitalRead(TOUCH_PIN)) + ",";
  s += "\"touch\":"      + String(digitalRead(TOUCH_PIN)) + ",";   // same as grip; the dashboard reads this name
  s += "\"moisture\":"   + String(analogRead(MOISTURE_PIN)) + ",";
  s += "\"hold_ms\":"    + String(int(core.lastHoldMs())) + ",";   // length of the last click
  s += "\"state\":"      + String(int(core.state())) + ",";   // 0 idle, 1 armed
  s += "\"i2c\":\""     + String(i2cFound) + "\"";            // addresses found on Wire1 at boot (debug)
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

// Linux polls this with the approval's digest. "1" only if a real click with the palm on the
// grip happened in the last 1.5 s (and we are not armed already or rate limited). Else "0".
String arm_approval(String digestHex) {
  uint8_t digest[32];
  int32_t f[yuseal::N_FEATURES];
  if (!fromHex(digestHex, digest, 32)) return "0";
  computeFeatures(f);
  return core.arm(digest, millis(), f) ? "1" : "0";
}

// "-" until armed, then the salt for the YubiKey. The same for every outcome.
String get_unlock_salt() {
  uint8_t salt[32];
  return core.unlockSalt(salt) ? toHex(salt, 32) : String("-");
}

// The click age, grip flag and sensor summary the tag will cover, as hex, or "-".
String get_attest() {
  uint8_t a[yuseal::Mcu::ATTEST_LEN];
  return core.attest(a) ? toHex(a, yuseal::Mcu::ATTEST_LEN) : String("-");
}

// Linux passes the model's score as a whole number 0..100 (anything else = no usable verdict).
// Returns the 32-byte tag as hex, or "-".
String seal_approval(String scoreStr, String vetoStr) {
  uint8_t tag[32];
  int score = scoreStr.toInt();
  if (!core.seal(score, vetoStr == "1", tag)) return "-";
  return toHex(tag, 32);
}

// ---------------- the profile (Linux -> STM32). The STM32 reads the sensors itself. ----------------
// The key that encrypts the profile on the Linux side. Derived here, never stored there.
String get_profile_key() {
  uint8_t k[32];
  core.profileKey(k);
  return toHex(k, 32);
}

static void bodyReadings(double v[yuseal::BL_SENSORS]) {   // order: humidity, moisture, shake_rms, temp_c
  v[0] = thermo.getHumidity();
  v[1] = analogRead(MOISTURE_PIN);
  v[2] = shakeRms();
  v[3] = thermo.getTemperature();
}

// Adds the CURRENT readings to this hour's baseline, but only while a palm is on the grip.
// Linux says which hour it is and nothing else, so it cannot feed in readings. "1" or "0".
String baseline_add(String hourStr) {
  if (digitalRead(TOUCH_PIN) != HIGH) return "0";
  double v[yuseal::BL_SENSORS];
  bodyReadings(v);
  baseline.add(hourStr.toInt(), v);
  return "1";
}

// z-scores of the current readings against this hour's baseline, "z0 z1 z2 z3", or "-" if too little data.
String baseline_z(String hourStr) {
  double v[yuseal::BL_SENSORS], z[yuseal::BL_SENSORS];
  bodyReadings(v);
  if (!baseline.z(hourStr.toInt(), v, z)) return "-";
  String s;
  for (int i = 0; i < yuseal::BL_SENSORS; i++) { if (i) s += " "; s += String(z[i], 4); }
  return s;
}

// One hour of statistics as hex (for the encrypted copy), and the same back in after a power cut.
String baseline_export(String hourStr) {
  uint8_t b[yuseal::BL_HOUR_BYTES];
  baseline.exportHour(hourStr.toInt(), b);
  return toHex(b, yuseal::BL_HOUR_BYTES);
}
String baseline_import(String hourStr, String hex) {
  uint8_t b[yuseal::BL_HOUR_BYTES];
  if (!fromHex(hex, b, yuseal::BL_HOUR_BYTES)) return "0";
  return baseline.importHour(hourStr.toInt(), b) ? "1" : "0";
}

void setup() {
  Monitor.begin(115200);
  Bridge.begin();
  Modulino.begin(Wire1);     // UNO Q's Qwiic connector is on Wire1 (as in Arduino's examples)
  scanI2C();
  thermo.begin();
  movement.begin();
#ifdef CLICK_FROM_MODULINO_BUTTON
  buttons.begin();
#else
  pinMode(CLICK_PIN, INPUT_PULLUP);
#endif
  // The DFRobot touch and moisture sensors take power from D7 / D8 (docs/HARDWARE.md):
  // the UNO Q has one 3V3 pin, and a shared joint there left both unpowered.
  pinMode(7, OUTPUT); digitalWrite(7, HIGH);   // touch VCC
  pinMode(8, OUTPUT); digitalWrite(8, HIGH);   // moisture VCC
  delay(300);                                  // the touch chip calibrates for ~0.25 s after power-up
  pinMode(TOUCH_PIN, INPUT);
  for (int i = 0; i < WIN; i++) mag[i] = 1.0;

  core.provision(YS_K_MCU);
  baseline.clear();

  Bridge.provide_safe("get_features", get_features);
  Bridge.provide_safe("arm_approval", arm_approval);
  Bridge.provide_safe("get_unlock_salt", get_unlock_salt);
  Bridge.provide_safe("get_attest", get_attest);
  Bridge.provide_safe("seal_approval", seal_approval);
  Bridge.provide_safe("get_profile_key", get_profile_key);
  Bridge.provide_safe("baseline_add", baseline_add);
  Bridge.provide_safe("baseline_z", baseline_z);
  Bridge.provide_safe("baseline_export", baseline_export);
  Bridge.provide_safe("baseline_import", baseline_import);   // VERIFY: two String arguments over Bridge
}

void loop() {
  bool grip = digitalRead(TOUCH_PIN) == HIGH;

  // 100 Hz accel sampling for the rolling window
  if (millis() - lastSample >= 10) {
    lastSample = millis();
    movement.update();
    float x = movement.getX(), y = movement.getY(), z = movement.getZ();
    float m = sqrt(x * x + y * y + z * z);
    float d = fabs(m - magPrev);
    magPrev = m;
    moveAbs = 0.95f * moveAbs + 0.05f * d;
    mag[magIdx] = m;
    stillWin[magIdx] = d < 0.02f;
    gripWin[magIdx] = grip;
    magIdx = (magIdx + 1) % WIN;
    if (millis() < impulseUntil && d > impulsePeak) impulsePeak = d;
  }

  // The click edges go straight to the trusted core. Linux never sees them.
#ifdef CLICK_FROM_MODULINO_BUTTON
  bool click = false;
  if (buttons.update()) click = buttons.isPressed(CLICK_BUTTON);
  else click = prevClick;
#else
  bool click = digitalRead(CLICK_PIN) == LOW;
#endif
  if (click && !prevClick) {
    impulsePeak = 0;
    impulseUntil = millis() + 60;
    core.clickDown(millis(), grip);
  }
  if (!click && prevClick) core.clickUp(millis());
  prevClick = click;

  core.tick(millis());
}
