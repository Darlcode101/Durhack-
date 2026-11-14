// YuSeal v2 trusted core for the STM32 side of the UNO Q. See docs/CRYPTO.md.
//
// Plain C++ with no Arduino dependencies, so the same file is compiled and tested
// on a laptop (tools/mcu_host_test.cpp) and checked against the Python model.
// It needs only SHA-256: no big-number maths, no heap, about 1 KB of RAM.
//
// What it guarantees, even if the Linux side is fully compromised:
//   * a tag is only produced after a correct PIN was pressed on the real buttons
//     for the text that was on the LED matrix (one tag per begin());
//   * the tag covers the SHA-256 of that text, computed here, not by Linux;
//   * the tag secretly says normal / step-up / duress, and Linux can't tell which.
#ifndef YUSEAL_MCU_H
#define YUSEAL_MCU_H

#include <stdint.h>
#include <string.h>

namespace yuseal {

// ------------------------------------------------------------------ SHA-256 (FIPS 180-4)
class Sha256 {
 public:
  Sha256() { reset(); }
  void reset() {
    static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(h_, iv, sizeof h_);
    len_ = 0;
    n_ = 0;
  }
  void update(const void* data, size_t len) {
    const uint8_t* p = static_cast<const uint8_t*>(data);
    len_ += len;
    while (len--) {
      buf_[n_++] = *p++;
      if (n_ == 64) { block(buf_); n_ = 0; }
    }
  }
  void finish(uint8_t out[32]) {
    uint64_t bits = len_ * 8;
    uint8_t pad = 0x80;
    update(&pad, 1);
    pad = 0;
    while (n_ != 56) update(&pad, 1);
    uint8_t lenb[8];
    for (int i = 0; i < 8; i++) lenb[i] = uint8_t(bits >> (56 - 8 * i));
    update(lenb, 8);
    for (int i = 0; i < 8; i++)
      for (int j = 0; j < 4; j++) out[4 * i + j] = uint8_t(h_[i] >> (24 - 8 * j));
  }

 private:
  static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
  void block(const uint8_t* b) {
    static const uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
      w[i] = uint32_t(b[4 * i]) << 24 | uint32_t(b[4 * i + 1]) << 16 | uint32_t(b[4 * i + 2]) << 8 | b[4 * i + 3];
    for (int i = 16; i < 64; i++) {
      uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h_[0], bb = h_[1], c = h_[2], d = h_[3], e = h_[4], f = h_[5], g = h_[6], h = h_[7];
    for (int i = 0; i < 64; i++) {
      uint32_t t1 = h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
      uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c));
      h = g; g = f; f = e; e = d + t1; d = c; c = bb; bb = a; a = t1 + t2;
    }
    h_[0] += a; h_[1] += bb; h_[2] += c; h_[3] += d; h_[4] += e; h_[5] += f; h_[6] += g; h_[7] += h;
  }
  uint32_t h_[8];
  uint64_t len_;
  uint8_t buf_[64];
  size_t n_;
};

// ------------------------------------------------------------------ HMAC-SHA-256 (RFC 2104), 32-byte keys
class Hmac {
 public:
  explicit Hmac(const uint8_t key[32]) {
    uint8_t pad[64];
    memset(pad, 0x36, 64);
    for (int i = 0; i < 32; i++) { pad[i] ^= key[i]; okey_[i] = key[i] ^ 0x5c; }
    memset(okey_ + 32, 0x5c, 32);
    inner_.update(pad, 64);
  }
  void update(const void* d, size_t n) { inner_.update(d, n); }
  void update(const char* s) { inner_.update(s, strlen(s)); }
  void finish(uint8_t out[32]) {
    uint8_t ih[32];
    inner_.finish(ih);
    Sha256 outer;
    outer.update(okey_, 64);
    outer.update(ih, 32);
    outer.finish(out);
  }

 private:
  Sha256 inner_;
  uint8_t okey_[64];
};

// Constant-time compare: takes the same time whether or not the bytes match.
inline bool equal32(const uint8_t* a, const uint8_t* b) {
  uint8_t diff = 0;
  for (int i = 0; i < 32; i++) diff |= a[i] ^ b[i];
  return diff == 0;
}

// ------------------------------------------------------------------ the approval state machine
const int MAX_TEXT = 96;        // longest display text we accept
const int MAX_PIN = 16;
const uint32_t LONG_PRESS_MS = 800;    // a press held this long is the lowercase symbol (A -> a)
const uint32_t SETTLE_MS = 1500;       // PIN is "ready" this long after the last press goes DOWN,
                                       // so Linux can't time how long the last button was held
const uint32_t SESSION_MS = 90000;     // begin() to seal() must fit in this
const int MAX_WRONG = 5;
const int STEP_UP_AT = 40, DURESS_AT = 70;   // Gemini score, 0..100

enum State : uint8_t { IDLE = 0, PIN_ENTRY = 1, PIN_OK = 2, LOCKED = 3 };
enum Status : char { NORMAL = 'N', STEP_UP = 'S', DURESS = 'D' };

class Mcu {
 public:
  // Called once at boot with the values from secrets.h (written by tools/provision.py).
  void provision(const uint8_t kMcu[32], const uint8_t pinTagNormal[32], const uint8_t pinTagDuress[32],
                 uint8_t pinLen) {
    derive(kMcu, "YS2/pin-key", kPin_);
    derive(kMcu, "YS2/tag-key", kTag_);
    memcpy(tagN_, pinTagNormal, 32);
    memcpy(tagD_, pinTagDuress, 32);
    pinLen_ = pinLen > MAX_PIN ? MAX_PIN : pinLen;
    clear();
  }

  // Step 1. Linux hands over the text to show and the approval's digest.
  // We hash the text ourselves. Returns false if we won't show it.
  bool begin(const char* text, const uint8_t coreDigest[32], uint32_t nowMs) {
    if (state_ == LOCKED) return false;
    size_t n = strlen(text);
    if (n == 0 || n > MAX_TEXT) return false;
    for (size_t i = 0; i < n; i++)
      if (text[i] < 0x20 || text[i] > 0x7e) return false;  // printable ASCII only
    clear();
    memcpy(text_, text, n + 1);
    Sha256 s;
    s.update(text, n);
    s.finish(displayHash_);
    memcpy(coreDigest_, coreDigest, 32);
    startMs_ = nowMs;
    state_ = PIN_ENTRY;
    return true;
  }

  // Step 2. The sketch reports real button edges. Presses only count while the grip is held.
  void buttonDown(char c, bool gripHeld, uint32_t nowMs) {
    if (state_ != PIN_ENTRY || !gripHeld || pinCount_ >= pinLen_ || c < 'A' || c > 'C') return;
    pin_[pinCount_++] = c;
    downMs_ = nowMs;
    held_ = true;
  }
  void buttonUp(uint32_t nowMs) {
    if (!held_) return;
    held_ = false;
    if (state_ == PIN_ENTRY && nowMs - downMs_ >= LONG_PRESS_MS) pin_[pinCount_ - 1] += 32;  // 'A' -> 'a'
  }

  // Call often from loop(). Finishes the PIN and enforces the session timeout.
  void tick(uint32_t nowMs) {
    if (state_ == PIN_ENTRY || state_ == PIN_OK) {
      if (nowMs - startMs_ > SESSION_MS) { clear(); return; }
    }
    if (state_ == PIN_ENTRY && pinCount_ == pinLen_ && nowMs - downMs_ >= SETTLE_MS) {
      if (held_) buttonUp(nowMs);  // still held after the settle time counts as a long press
      classify();
    }
  }

  // Step 3. After a correct PIN (normal OR duress: same answer), release the salt that
  // lets Linux ask the YubiKey for the key-unlocking secret. Wrong PIN: nothing.
  bool unlockSalt(uint8_t out[32]) {
    if (state_ != PIN_OK) return false;
    Hmac h(kPin_);
    h.update("unlock-salt");
    h.finish(out);
    return true;
  }

  // Step 4. Linux passes Gemini's score (0..100, anything else = no usable verdict).
  // We decide the status and return the tag. Works once per begin().
  bool seal(int score, bool veto, uint8_t tagOut[32]) {
    if (state_ != PIN_OK) return false;
    char status = decide(duressPin_, score, veto);
    Hmac h(kTag_);
    h.update("YS2/tag");
    h.update(&status, 1);
    h.update(displayHash_, 32);
    h.update(coreDigest_, 32);
    h.finish(tagOut);
    clear();
    return true;
  }

  // The one decision rule. Gemini can raise the alarm, never lower it. Fail closed.
  static char decide(bool duressPin, int score, bool veto) {
    if (duressPin || veto) return DURESS;
    if (score < 0 || score > 100) return DURESS;
    if (score >= DURESS_AT) return DURESS;
    if (score >= STEP_UP_AT) return STEP_UP;
    return NORMAL;
  }

  State state() const { return state_; }
  int pinCount() const { return pinCount_; }
  const char* text() const { return text_; }
  int wrongCount() const { return wrong_; }

 private:
  static void derive(const uint8_t key[32], const char* label, uint8_t out[32]) {
    Hmac h(key);
    h.update(label);
    h.finish(out);
  }
  void classify() {
    uint8_t t[32];
    Hmac h(kPin_);
    h.update("pin|");
    h.update(pin_, pinCount_);
    h.finish(t);
    bool n = equal32(t, tagN_), d = equal32(t, tagD_);  // always check both
    memset(pin_, 0, sizeof pin_);
    if (n || d) {
      duressPin_ = d;
      wrong_ = 0;
      state_ = PIN_OK;
    } else {
      wrong_++;
      bool lock = wrong_ >= MAX_WRONG;
      clear();
      if (lock) state_ = LOCKED;  // until power cycle; a guardian unlock is future work
    }
  }
  void clear() {
    memset(pin_, 0, sizeof pin_);
    memset(text_, 0, sizeof text_);
    pinCount_ = 0;
    held_ = false;
    duressPin_ = false;
    state_ = IDLE;
  }

  uint8_t kPin_[32], kTag_[32], tagN_[32], tagD_[32];
  uint8_t displayHash_[32], coreDigest_[32];
  char text_[MAX_TEXT + 1];
  char pin_[MAX_PIN + 1];
  uint8_t pinLen_ = 0, pinCount_ = 0;
  int wrong_ = 0;
  bool held_ = false, duressPin_ = false;
  uint32_t startMs_ = 0, downMs_ = 0;
  State state_ = IDLE;
};

}  // namespace yuseal
#endif
