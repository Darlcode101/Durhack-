// Laptop test for app/sketch/yuseal_mcu.h. Built and run by app/python/test_yuseal.py.
//   g++ -std=c++17 -I app/sketch tools/mcu_host_test.cpp -o /tmp/mcu_host_test
// Reads commands on stdin, prints results, so Python can drive the real C++ core:
//   provision <kmcu hex>
//   down <grip 0|1> <nowMs>     up <nowMs>     tick <nowMs>
//   arm <digest hex> <nowMs> <f0> ... <f9>      (prints 1 or 0)
//   profile        (the profile key, hex)
//   bl_add <hour> <v0..v3>   bl_z <hour> <v0..v3>   bl_export <hour>   bl_import <hour> <hex>   bl_count <hour>
//   salt        attest        seal <score> <veto 0|1>        state        sha <text>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include "yuseal_mcu.h"
#include "baseline_mcu.h"

static void unhex(const std::string& s, uint8_t* out) {
  for (int i = 0; i < 32; i++) out[i] = uint8_t(std::stoi(s.substr(2 * i, 2), nullptr, 16));
}
static void hex(const uint8_t* b, int n = 32) {
  for (int i = 0; i < n; i++) printf("%02x", b[i]);
  printf("\n");
}

int main() {
  yuseal::Mcu mcu;
  yuseal::HourBaseline bl;
  bl.clear();
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    in >> cmd;
    uint8_t a[32];
    if (cmd == "provision") {
      std::string k;
      in >> k;
      unhex(k, a);
      mcu.provision(a);
      printf("ok\n");
    } else if (cmd == "down") {
      int grip; uint32_t now;
      in >> grip >> now;
      mcu.clickDown(now, grip != 0);
      printf("ok\n");
    } else if (cmd == "up") {
      uint32_t now; in >> now; mcu.clickUp(now); printf("ok\n");
    } else if (cmd == "tick") {
      uint32_t now; in >> now; mcu.tick(now); printf("ok\n");
    } else if (cmd == "arm") {
      std::string dg; uint32_t now; int32_t f[yuseal::N_FEATURES];
      in >> dg >> now;
      for (int i = 0; i < yuseal::N_FEATURES; i++) in >> f[i];
      unhex(dg, a);
      printf("%d\n", mcu.arm(a, now, f) ? 1 : 0);
    } else if (cmd == "salt") {
      if (mcu.unlockSalt(a)) hex(a); else printf("-\n");
    } else if (cmd == "attest") {
      uint8_t buf[yuseal::Mcu::ATTEST_LEN];
      if (mcu.attest(buf)) hex(buf, yuseal::Mcu::ATTEST_LEN); else printf("-\n");
    } else if (cmd == "seal") {
      int score, veto; in >> score >> veto;
      if (mcu.seal(score, veto != 0, a)) hex(a); else printf("-\n");
    } else if (cmd == "state") {
      printf("%d %d\n", int(mcu.state()), int(mcu.lastHoldMs()));
    } else if (cmd == "profile") {
      mcu.profileKey(a); hex(a);
    } else if (cmd == "bl_add" || cmd == "bl_z") {
      int hour; double v[yuseal::BL_SENSORS], z[yuseal::BL_SENSORS];
      in >> hour;
      for (int i = 0; i < yuseal::BL_SENSORS; i++) in >> v[i];
      if (cmd == "bl_add") { bl.add(hour, v); printf("ok\n"); }
      else if (bl.z(hour, v, z)) { for (int i = 0; i < yuseal::BL_SENSORS; i++) printf("%.10g%c", z[i], i + 1 < yuseal::BL_SENSORS ? ' ' : '\n'); }
      else printf("-\n");
    } else if (cmd == "bl_export") {
      int hour; in >> hour; uint8_t b[yuseal::BL_HOUR_BYTES]; bl.exportHour(hour, b); hex(b, yuseal::BL_HOUR_BYTES);
    } else if (cmd == "bl_import") {
      int hour; std::string h; in >> hour >> h; uint8_t b[yuseal::BL_HOUR_BYTES];
      for (int i = 0; i < yuseal::BL_HOUR_BYTES; i++) b[i] = uint8_t(std::stoi(h.substr(2 * i, 2), nullptr, 16));
      printf("%d\n", bl.importHour(hour, b) ? 1 : 0);
    } else if (cmd == "bl_count") {
      int hour; in >> hour; printf("%d\n", bl.count(hour));
    } else if (cmd == "sha") {
      std::string text; std::getline(in, text);
      if (!text.empty() && text[0] == ' ') text.erase(0, 1);
      yuseal::Sha256 s; s.update(text.data(), text.size()); s.finish(a); hex(a);
    }
    fflush(stdout);
  }
}
