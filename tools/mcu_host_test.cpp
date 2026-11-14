// Laptop test for app/sketch/yuseal_mcu.h. Built and run by app/python/test_yuseal.py.
//   g++ -std=c++17 -I app/sketch tools/mcu_host_test.cpp -o /tmp/mcu_host_test
// Reads commands on stdin, prints results, so Python can drive the real C++ core:
//   provision <kmcu hex> <tagN hex> <tagD hex> <pinLen>
//   begin <coreDigest hex> <nowMs> <text...>
//   down <A|B|C> <grip 0|1> <nowMs>      up <nowMs>      tick <nowMs>
//   salt                                  seal <score> <veto 0|1>      state
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include "yuseal_mcu.h"

static void unhex(const std::string& s, uint8_t* out) {
  for (int i = 0; i < 32; i++) out[i] = uint8_t(std::stoi(s.substr(2 * i, 2), nullptr, 16));
}
static void hex(const uint8_t* b) {
  for (int i = 0; i < 32; i++) printf("%02x", b[i]);
  printf("\n");
}

int main() {
  yuseal::Mcu mcu;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    in >> cmd;
    uint8_t a[32], b[32], c[32];
    if (cmd == "provision") {
      std::string k, n, d; int len;
      in >> k >> n >> d >> len;
      unhex(k, a); unhex(n, b); unhex(d, c);
      mcu.provision(a, b, c, uint8_t(len));
      printf("ok\n");
    } else if (cmd == "begin") {
      std::string dg, text; uint32_t now;
      in >> dg >> now;
      std::getline(in, text);
      if (!text.empty() && text[0] == ' ') text.erase(0, 1);
      unhex(dg, a);
      printf("%d\n", mcu.begin(text.c_str(), a, now) ? 1 : 0);
    } else if (cmd == "down") {
      char ch; int grip; uint32_t now;
      in >> ch >> grip >> now;
      mcu.buttonDown(ch, grip != 0, now);
      printf("ok\n");
    } else if (cmd == "up") {
      uint32_t now; in >> now; mcu.buttonUp(now); printf("ok\n");
    } else if (cmd == "tick") {
      uint32_t now; in >> now; mcu.tick(now); printf("ok\n");
    } else if (cmd == "salt") {
      if (mcu.unlockSalt(a)) hex(a); else printf("-\n");
    } else if (cmd == "seal") {
      int score, veto; in >> score >> veto;
      if (mcu.seal(score, veto != 0, a)) hex(a); else printf("-\n");
    } else if (cmd == "state") {
      printf("%d %d\n", int(mcu.state()), mcu.pinCount());
    } else if (cmd == "sha") {
      std::string text; std::getline(in, text);
      if (!text.empty() && text[0] == ' ') text.erase(0, 1);
      yuseal::Sha256 s; s.update(text.data(), text.size()); s.finish(a); hex(a);
    }
    fflush(stdout);
  }
}
