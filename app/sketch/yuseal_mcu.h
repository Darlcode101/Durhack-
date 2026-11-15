// YuSeal v3 (mouse mode) trusted core for the STM32 side of the UNO Q.
// See docs/STEALTH-APPROVAL.md and docs/OWNER-CHECK.md.
//
// Plain C++ with no Arduino dependencies, so the same file is compiled and tested
// on a laptop (tools/mcu_host_test.cpp) and checked against the Python model.
// It needs only SHA-256: no big-number maths, no heap, about 1 KB of RAM.
//
// There is no screen and no PIN. The user does nothing extra: the physical click on the mouse's
// switch (read by the STM32 through a read-only tap) is the trigger. What it guarantees, even if
// the Linux side is fully compromised:
//   * a tag is only produced after Linux armed us within CLICK_WINDOW_MS of a real click with the
//     palm on the grip (one tag per click, rate limited);
//   * the tag covers the request digest, the click's age, the grip flag and a hash of the sensor
//     summary, so Linux can't swap the sensor data (the verifier re-checks it);
//   * the tag secretly says normal / step-up / duress, and Linux can't tell which.
// Duress is decided only from the model's score and the onboard veto: there is no duress PIN.
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
const int N_FEATURES = 10;                 // the sensor summary the tag covers (see yuseal.py FEATURE_NAMES)
const uint32_t CLICK_WINDOW_MS = 1500;     // arm() must come this soon after a real click
const uint32_t SESSION_MS = 30000;         // arm() to seal() must fit in this
const int RATE_MAX = 10;                   // at most this many arms ...
const uint32_t RATE_WINDOW_MS = 600000;    // ... per ten minutes
const int STEP_UP_AT = 40, DURESS_AT = 70; // model score, 0..100

enum State : uint8_t { IDLE = 0, ARMED = 1 };
enum Status : char { NORMAL = 'N', STEP_UP = 'S', DURESS = 'D' };

class Mcu {
 public:
  // Called once at boot with K_MCU from secrets.h (written by tools/provision.py).
  void provision(const uint8_t kMcu[32]) {
    derive(kMcu, "YS3/release-key", kRel_);
    derive(kMcu, "YS3/tag-key", kTag_);
    derive(kMcu, "YS3/profile-key", kProf_);
    nArms_ = head_ = 0;
    haveClick_ = pressed_ = false;
    clear();
  }

  // The sketch reports the real switch edges. gripHeld is the palm sensor at that moment.
  void clickDown(uint32_t nowMs, bool gripHeld) {
    if (pressed_) return;
    pressed_ = true;
    downMs_ = nowMs;
    clickMs_ = nowMs;
    clickGrip_ = gripHeld;
    haveClick_ = true;
  }
  void clickUp(uint32_t nowMs) {
    if (!pressed_) return;
    pressed_ = false;
    uint32_t hold = nowMs - downMs_;
    lastHoldMs_ = hold > 65535 ? 65535 : uint16_t(hold);
  }

  // Linux arms us with the approval's digest and the sensor summary (computed here by the sketch).
  // Refused unless a real click with the palm on the grip happened in the last CLICK_WINDOW_MS,
  // we are not already armed, and we have not been armed too often.
  bool arm(const uint8_t coreDigest[32], uint32_t nowMs, const int32_t features[N_FEATURES]) {
    if (state_ == ARMED || !haveClick_ || !clickGrip_) return false;
    uint32_t age = nowMs - clickMs_;
    if (age > CLICK_WINDOW_MS) return false;
    if (nArms_ == RATE_MAX && nowMs - armTimes_[head_] < RATE_WINDOW_MS) return false;
    armTimes_[head_] = nowMs;
    head_ = (head_ + 1) % RATE_MAX;
    if (nArms_ < RATE_MAX) nArms_++;
    memcpy(coreDigest_, coreDigest, 32);
    memcpy(features_, features, sizeof features_);
    clickAge_ = uint16_t(age);
    haveClick_ = false;  // one click arms once
    armMs_ = nowMs;
    state_ = ARMED;
    return true;
  }

  // Call often from loop(). Enforces the session timeout.
  void tick(uint32_t nowMs) {
    if (state_ == ARMED && nowMs - armMs_ > SESSION_MS) clear();
  }

  // Release the salt that lets Linux ask the YubiKey for the key-unlocking secret.
  // Same salt for every outcome, so Linux learns nothing about the result.
  // The key that encrypts the profile (baseline and model) at rest on the board's Linux side.
  // Derived here from K_MCU, never stored on Linux, and not tied to an approval, because the
  // baseline is learned all day. It reveals nothing about any decision or status.
  void profileKey(uint8_t out[32]) const { memcpy(out, kProf_, 32); }

  bool unlockSalt(uint8_t out[32]) {
    if (state_ != ARMED) return false;
    Hmac h(kRel_);
    h.update("unlock-salt");
    h.finish(out);
    return true;
  }

  // What the tag will cover, for Linux to put in the envelope: click age (2 bytes, big endian),
  // grip (1 byte), then the features as big-endian int32. Linux can't change them without
  // breaking the tag. out must hold ATTEST_LEN bytes.
  static const int ATTEST_LEN = 3 + 4 * N_FEATURES;
  bool attest(uint8_t out[ATTEST_LEN]) const {
    if (state_ != ARMED) return false;
    out[0] = uint8_t(clickAge_ >> 8);
    out[1] = uint8_t(clickAge_);
    out[2] = 1;
    featureBytes(out + 3);
    return true;
  }

  // Linux passes the model's score (0..100, anything else = no usable verdict) and the onboard veto.
  // We decide the status and return the tag. Works once per arm().
  bool seal(int score, bool veto, uint8_t tagOut[32]) {
    if (state_ != ARMED) return false;
    char status = decide(score, veto);
    uint8_t fb[4 * N_FEATURES], fh[32];
    featureBytes(fb);
    Sha256 fs;
    fs.update("YS3/features", 12);
    fs.update(fb, sizeof fb);
    fs.finish(fh);
    uint8_t ca[2] = {uint8_t(clickAge_ >> 8), uint8_t(clickAge_)};
    uint8_t grip = 1;
    Hmac h(kTag_);
    h.update("YS3/tag");
    h.update(&status, 1);
    h.update(coreDigest_, 32);
    h.update(ca, 2);
    h.update(&grip, 1);
    h.update(fh, 32);
    h.finish(tagOut);
    clear();
    return true;
  }

  // The one decision rule. The model can raise the alarm, never lower it. Fail closed.
  static char decide(int score, bool veto) {
    if (veto) return DURESS;
    if (score < 0 || score > 100) return DURESS;
    if (score >= DURESS_AT) return DURESS;
    if (score >= STEP_UP_AT) return STEP_UP;
    return NORMAL;
  }

  State state() const { return state_; }
  uint16_t lastHoldMs() const { return lastHoldMs_; }  // how long the last click was held (a feature)

 private:
  static void derive(const uint8_t key[32], const char* label, uint8_t out[32]) {
    Hmac h(key);
    h.update(label);
    h.finish(out);
  }
  void featureBytes(uint8_t* out) const {
    for (int i = 0; i < N_FEATURES; i++) {
      uint32_t v = uint32_t(features_[i]);
      out[4 * i] = uint8_t(v >> 24);
      out[4 * i + 1] = uint8_t(v >> 16);
      out[4 * i + 2] = uint8_t(v >> 8);
      out[4 * i + 3] = uint8_t(v);
    }
  }
  void clear() {
    memset(features_, 0, sizeof features_);
    state_ = IDLE;
  }

  uint8_t kRel_[32], kTag_[32], kProf_[32], coreDigest_[32];
  int32_t features_[N_FEATURES];
  uint32_t armTimes_[RATE_MAX];
  int nArms_ = 0, head_ = 0;
  bool pressed_ = false, haveClick_ = false, clickGrip_ = false;
  uint32_t downMs_ = 0, clickMs_ = 0, armMs_ = 0;
  uint16_t clickAge_ = 0, lastHoldMs_ = 0;
  State state_ = IDLE;
};

}  // namespace yuseal
#endif
