// The STM32's rolling per-hour baseline of the four body sensors (docs/EDGE-IMPULSE.md).
// For each hour of the day and each sensor it keeps an exponentially-weighted mean and variance:
// exact (mean, population variance) for the first BL_CAP samples, then a rolling window of about
// BL_CAP samples, so it follows slow drift. The STM32 reads the sensors itself, so Linux can only
// say which hour it is; it cannot feed in readings. Tested against yuseal.py's HourBaseline.
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>

namespace yuseal {

const int BL_SENSORS = 4;            // humidity, moisture, shake_rms, temp_c (this order)
const int BL_HOURS = 24;
const int BL_CAP = 1000;             // rolling window, in samples
const int BL_MIN_N = 20;             // no z-score before this many samples in an hour
const int BL_HOUR_BYTES = BL_SENSORS * 18;   // per sensor: n u16 LE, mean f64 LE, var f64 LE

class HourBaseline {
 public:
  void clear() { memset(s_, 0, sizeof s_); }

  void add(int hour, const double v[BL_SENSORS]) {
    if (hour < 0 || hour >= BL_HOURS) return;
    for (int i = 0; i < BL_SENSORS; i++) {
      Stat& s = s_[hour][i];
      if (s.n < BL_CAP) s.n++;
      double alpha = 1.0 / s.n, delta = v[i] - s.mean;
      s.mean += alpha * delta;
      s.var = (1.0 - alpha) * (s.var + alpha * delta * delta);
    }
  }

  // z-scores of v against this hour's baseline. False if the hour has too little data.
  bool z(int hour, const double v[BL_SENSORS], double out[BL_SENSORS]) const {
    if (hour < 0 || hour >= BL_HOURS) return false;
    for (int i = 0; i < BL_SENSORS; i++) {
      const Stat& s = s_[hour][i];
      if (s.n < BL_MIN_N) return false;
      double sd = sqrt(s.var), floor_ = 1e-3 * (1.0 + fabs(s.mean));
      out[i] = (v[i] - s.mean) / (sd > floor_ ? sd : floor_);
    }
    return true;
  }

  // One hour as bytes, for the encrypted copy on Linux (and to restore from after a power cut).
  void exportHour(int hour, uint8_t out[BL_HOUR_BYTES]) const {
    for (int i = 0; i < BL_SENSORS; i++) {
      const Stat& s = s_[hour][i];
      uint8_t* p = out + 18 * i;
      p[0] = uint8_t(s.n); p[1] = uint8_t(s.n >> 8);
      memcpy(p + 2, &s.mean, 8);     // little-endian on the STM32 and on x86/ARM laptops
      memcpy(p + 10, &s.var, 8);
    }
  }
  bool importHour(int hour, const uint8_t in[BL_HOUR_BYTES]) {
    if (hour < 0 || hour >= BL_HOURS) return false;
    for (int i = 0; i < BL_SENSORS; i++) {
      const uint8_t* p = in + 18 * i;
      uint16_t n = uint16_t(p[0] | (p[1] << 8));
      if (n > BL_CAP) return false;
      Stat t; t.n = n; memcpy(&t.mean, p + 2, 8); memcpy(&t.var, p + 10, 8);
      if (!(t.var >= 0) || !isfinite(t.mean) || !isfinite(t.var)) return false;
      s_[hour][i] = t;
    }
    return true;
  }
  int count(int hour) const { return (hour < 0 || hour >= BL_HOURS) ? 0 : s_[hour][0].n; }

 private:
  struct Stat { uint16_t n; double mean, var; };
  Stat s_[BL_HOURS][BL_SENSORS];
};

}  // namespace yuseal
