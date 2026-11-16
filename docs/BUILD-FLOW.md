# YuDuino build flow: hardware and code together

> **Historical (DurHack working doc).** Written during the hackathon. Parts describe the earlier PIN-and-LED-matrix design, Gemini/Tiger Data, or add-ons we didn't build (ElevenLabs, Solana, MongoDB). The final design, as presented, is in the [README](../README.md), the [overview](YuDuino-Overview.md) and the [pitch deck](../presentation/YuDuino-DurHack-2026-pitch.pdf).

*Written 14 November 2026, evening of day one of DurHack.* This page answers one question: **for each piece of hardware, what do I code, in which file, in which language, on which chip, and how do I know it works?** Back to the **[crypto design](CRYPTO.md)** · **[hardware plan](HARDWARE-PLAN.md)** (wiring) · **[dev plan](DEV-PLAN.md)** (the waves).

## 1. The map: three computers, one rule

```
┌──────────────────────────── Arduino UNO Q ─────────────────────────────┐
│                                                                        │
│  STM32U585 (C++, app/sketch/)              Linux, QRB2210 (Python, app/python/)
│  ───────────────────────────               ─────────────────────────────────────
│  yuseal_mcu.h  trusted core                main.py      entry: enrol / approve
│  sketch.ino    glue: click tap, sensors,   approve.py   one approval, step by step
│                Bridge calls                yuseal.py    envelope + crypto + owner check
│       ▲                                    yubikey_auth.py  YubiKey over USB
│       │ Bridge (remote calls)              camera.py, edge_model.py  Edge Impulse
│       └────────────────────────────────────────┘
│  owns: click tap, Movement,              owns: USB hub → YubiKey + camera + mic,
│        Thermo, touch D2, moisture A1,           the Edge Impulse model, on the board
│        tag key
└────────────────────────────────────────────────────────────────────────┘
                                   │ envelope
                                   ▼
        The customer's system: it sends the request and a nonce, and checks the envelope
        with the reference verifier (`Verifier` in yuseal.py). YuDuino is only the authenticator.
```

**The one rule:** the click, the grip, the sensor summary the tag covers and the status (normal / step-up / duress) are handled **only by the STM32**. Linux asks it questions and relays answers, but never sees a click edge. If you ever write code that decides the duress status on Linux, or tells the STM32 a click happened, you have broken the design. (That is exactly what the old `main.py` did; it has been replaced.)

## 2. What to code where, file by file

| File | Chip and language | Job | State |
|---|---|---|---|
| `app/sketch/yuseal_mcu.h` | STM32, C++ | The trusted core: SHA-256, HMAC, click and grip rule, arm, rate limit, status rule, tag | **Done and tested** on a laptop against Python. Don't edit unless you also change `yuseal.py` and `test_yuseal.py` |
| `app/sketch/sketch.ino` | STM32, C++ | Glue: reads the click tap and sensors, computes the ten features, calls the core, exposes Bridge calls | Written, **not yet run on the board**. Four `VERIFY` marks (below) |
| `tools/provision.py` | Laptop, Python | Makes the STM32's secrets (`secrets.h`) and the verifier's tag key | Done and runs |
| `app/python/yuseal.py` | Linux and the customer's verifier, Python | The envelope, checks, owner check, key store, audit log; the reference `Verifier` library | **Done and tested** |
| `app/python/approve.py` | Linux, Python | The step-by-step flow of one approval and of enrolment | Done, tested with a fake STM32 and YubiKey |
| `app/python/verify_cli.py` | Laptop, Python | A tiny reference verifier for trying it: `enrol`, `nonce`, `check` | Done |
| `app/python/yubikey_auth.py` | Linux, Python | `RealYubiKey`: the real YubiKey over USB | Written, **not yet run on hardware** |
| `app/python/main.py` | Linux, Python | `enrol` and `approve` commands, wires everything together | Written, not run on hardware |
| `app/python/edge_model.py`, `camera.py` | Linux, Python | The on-device Edge Impulse model (the generic model, installed per user and encrypted), camera frame | `model_fn` in `main.py` calls them. Needs a trained model per person ([EDGE-IMPULSE.md](EDGE-IMPULSE.md)) |

**Your actual coding work** is therefore small and concentrated. In order:

1. Make the four `VERIFY` items in `sketch.ino` work on the real board (§5).
2. Make `RealYubiKey` work on the real YubiKey (§5).
3. Wave 2: feed real sensor windows to the Edge Impulse model (`model_fn`) and tune the onboard veto limits (`onboard_veto` in `approve.py`).
4. Wave 3: dashboard and local store; the mouse shell.
5. Wave 4: readout protection, SLH-DSA root, Solana.

You never have to write cryptography, only call it.

## 3. The flow, wave by wave: hardware step, code step, test

Each row is one sitting. Don't move on until the **Test** passes. All commands run from the repository root unless stated.

### Before the board: check the code on your laptop (10 minutes, do this first)

```bash
pip install -r app/python/requirements.txt fastapi httpx
cd app/python && python3 -m unittest test_yuseal -v
```

**Test:** 57 tests pass. (The C++ tests need `g++`; they're skipped without it.) If this fails on your laptop, stop and fix it before touching hardware.

### Wave 1: skeleton (19:30 to 23:30)

| # | Hardware step ([hardware plan](HARDWARE-PLAN.md)) | Code step | Test |
|---|---|---|---|
| 1 | **Step 0 to 1:** power, hub, board on Wi-Fi; tap the donor mouse's left switch | Upload `step1_click` | DOWN/UP print on each click, `grip=1` with a palm on the mouse, the mouse still works |
| 2 | **Step 2:** Qwiic chain: Thermo, Movement (Buttons only as a bench click) | Check `Modulino.begin()` and the calls in `loop()` | Thermo and accel values print |
| 3 | **Step 3:** touch on D2, moisture on A1 | Nothing new; `digitalRead(TOUCH_PIN)` is the grip check | Touch pad reads 1 when held |
| 4 | *(laptop)* | `python3 tools/provision.py` | Prints "Wrote app/sketch/secrets.h…" |
| 5 | Flash `sketch.ino` (with the new `secrets.h`) from App Lab | Check that `Bridge.provide_safe()` accepts the handlers with String arguments (§5, item 1) | From the Linux side, `Bridge.call("get_features")` returns JSON with `grip` and `state` |
| 6 | *(laptop or board)* | `cd app/python && python3 verify_cli.py nonce` (the reference verifier) | Prints a one-time nonce |
| 7 | **Step 6, basic route:** YubiKey plugged into the hub | Make `RealYubiKey` work (§5, item 4). Run `python3 main.py enrol jonah > package.json` and click once (no touch if the key allows it, §5 item 4), then `python3 verify_cli.py enrol jonah package.json` | Prints `enrolled jonah` |
| 8 | **Milestone 1** | `python3 main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2…"}' --nonce <nonce> > envelope.json`, then `python3 verify_cli.py check envelope.json request.json` | click with your palm on the mouse within a few seconds; the check prints `"public": "accepted"` and `"verdict": "normal"` |
| 9 | | Repeat with a shaking hand, or a second face in the camera | The check still prints `"public": "accepted"`, but `"verdict": "duress"` |
| 10 | | Unplug the Wi-Fi from the board (or remove the model file and stop the dashboard) and approve normally | The verdict is `duress`: no model verdict means duress |

**Done when** rows 8, 9 and 10 pass. That is the Wave 1 demo, and it's the whole core idea: calm approves, coerced and "no model" both hold, and from outside they look identical. Commit and tag `wave-1`.

### Wave 2: real signals (23:30 to 03:30)

| Hardware step | Code step | Test |
|---|---|---|
| Sensors into the cardboard grip; tape every joint | None | A loose wire mid-demo trips the veto; tape it |
| **All-day baseline** ([BASELINE.md](BASELINE.md)): STM32 computes a per-minute row (grip fraction, 4 to 12 Hz tremor from quiet windows only, humidity delta, moisture, still fraction); the dashboard writes it to the local store | Rows appear every minute only while the hand is on a still-enough mouse; no raw data in the table |
| Baseline lookup by hour of day, with fallbacks | The dashboard returns the hour bucket (median and spread), falls back to the whole day and then the population prior, and passes it to the on-device model | The dashboard shows the baseline filling in; sparse hours fall back |
| One-minute calm baseline | In `main.py enrol`, record `capture_window(30)`-style readings into `device.json`; save to the local store | Baseline row appears in the store |
| Camera and microphone on the hub | `model_fn` in `main.py` already gets a face count from the camera; add the mic features to the vector (`edge_model.FEATURE_NAMES`) | `model_fn` returns `duress_score` for a calm and a shaky approval |
| Calm vs. shaking approvals | Put each reading as a **delta from the baseline** in the model's feature vector | Calm gives a low score, shaking and a second face give a high one, with reasons |
| | Tune the limits in `onboard_veto` (`approve.py`) to your real sensors | An unplugged Thermo triggers `veto` |
| | Try to persist the arming rate-limit history in the STM32's flash (§5, item 5). If it can't, say so in the write-up | After a power cycle the rate limit is still remembered |

**Done when** the same person approving calmly and then shaking gets different verdicts with sensible reasons, and replaying an old envelope is rejected (run `verify_cli.py check` twice on the same envelope). Tag `wave-2`.

### Wave 3: response and polish (03:30 to 07:30)

| Hardware step | Code step | Test |
|---|---|---|
| Donor mouse with a read-only switch tap, then the base plate and inserts ([MOUSE-DESIGN.md](MOUSE-DESIGN.md)); YubiKey and camera in the dock | `sketch.ino`: tremor filter (4 to 12 Hz) and skip while the mouse is moving or around a key press | The mouse still works as a mouse; the STM32 logs every click; the approval flow works from inside the shell with a hand on it; Wi-Fi holds |
| | Optional: YubiKey attestation at enrolment (`attestation="direct"`) | A software "YubiKey" can't enrol |
| | ElevenLabs reads **only the request text** aloud | Same speech for normal and duress |

**Done when** the mouse shell works end to end and a coerced approval looks normal on the device but reads `duress` to the verifier. Tag `wave-3`.

### Wave 4: harden and stretch (07:30 to 10:30)

| Hardware step | Code step | Test |
|---|---|---|
| Sealed shell screws; spare cables | Lock the STM32's debug port and enable readout protection if the toolchain allows | Flash can't be read through the debug port |
| | Check `openssl version` is 3.5+ on the board; test that TLS to the verifier negotiates `X25519MLKEM768` | `openssl s_client -groups X25519MLKEM768 …` succeeds |
| | Rehearse the Binance-replay demo twice; record a backup video | Runs start to finish without touching a laptop, twice |
| | Stretch: Solana devnet program checks the envelope and releases or freezes funds | A normal approval releases, a duress approval freezes on chain |

## 4. Who codes what

The same four roles as the [dev plan](DEV-PLAN.md#who-does-what-team-of-4), now with files:

| Role | Files | First job |
|---|---|---|
| **1. Microcontroller and sensors** | `sketch.ino` (and `yuseal_mcu.h` only with someone else reviewing) | Rows 1 to 5 of Wave 1: click tap, Qwiic, Bridge calls |
| **2. Linux side and the model** | `main.py`, `approve.py` (`model_fn`, `onboard_veto`), `camera.py`, `edge_model.py`, `yubikey_auth.py` | Row 7: `RealYubiKey` on the real key; then `model_fn` |
| **3. Crypto and verifier** | `yuseal.py`, `verify_cli.py`, `tools/provision.py` | Rows 4 and 6; then the dashboard |
| **4. Build and pitch** | the mouse shell, dashboard look, demo script, video | Print the mouse shell; write the demo script from §6 |

**Review rule:** any change to `yuseal_mcu.h`, `yuseal.py` or the tag format needs the tests to pass and a second person to read it. Everything else can move fast.

## 5. Things we couldn't check without the board, and what to do if they fail

| # | Unverified | Where | If it doesn't work |
|---|---|---|---|
| 1 | `Bridge.provide()` accepts handlers with **String arguments** and `Bridge.call(name, a, b)` passes them | `sketch.ino`, `main.py` (`_Bridge`) | Pack the arguments into one String (`"text\|digest"`), split it in the sketch, and change `_Bridge.call` to join them |
| 2 | The **click tap** (idle level and polarity) | `CLICK_PIN` in `sketch.ino` | Swap the polarity in the sketch, or use `CLICK_FROM_MODULINO_BUTTON` for a bench click |
| 3 | The **Buttons** API (`update()`, `isPressed(i)`), used only for the bench click | `loop()` | Use the library's press and release callbacks and call `core.clickDown(millis(), grip)` and `core.clickUp(millis())` from them |
| 4 | **`RealYubiKey`**: whether the YubiKey 5 returns its hmac-secret **without a touch** (CTAP2 `up=false`, now done through the raw `Ctap2` API; run `tools/yk_probe.py`). **Fallback:** `YK_MODE=hmac-sha1`, the YubiKey's challenge-response slot set up without touch by `tools/setup_yk_hmac.py` (weaker: the verifier holds the slot key), and python-fido2 returning the raw authenticator data, client data and signature, with our challenge; USB access to `/dev/hidraw*` from inside App Lab | `yubikey_auth.py` | Run `main.py` as a normal process over SSH, not inside the App Lab container, with a udev rule for Yubico. **Fallback:** keep the YubiKey in the laptop and run a 30-line relay there that exposes the same two methods (`register`, `assert_and_secret`) behind an SSH tunnel; `approve.py` doesn't care |
| 5 | **Persistent storage** on the STM32 (for the arming rate-limit history) | not written yet | Keep it in RAM (already so); say in the write-up that power-cycling resets it, and rely on the verifier's repeat lock |
| 6 | `millis()` is monotonic and doesn't wrap during an approval | `yuseal_mcu.h` | It wraps after about 50 days; reboot before the demo |
| 7 | The board has **no hardware random number generator exposed to the sketch** | not needed | The design needs no randomness on the STM32: all its secrets come from `provision.py` |

The first time any of these runs, tell the team and tick it off in [PLAN.md](PLAN.md#things-to-verify-in-hour-02-not-yet-tested-on-hardware).

## 6. The demo, in order

1. **The Binance replay.** On the laptop, an attack script posts a transfer with no envelope. The verifier has nothing to check, so nothing is authorised.
2. **The legitimate request.** The script asks properly, with a nonce. You click "Process transaction" with the mouse like any other button. Nothing else. The verifier accepts it.
3. **The swap.** Change the destination after approval. The verifier rejects it (request hash).
4. **The replay.** Send the same envelope again. Rejected (nonce used).
5. **The coerced approval.** A teammate stands behind you, hand on your shoulder, hand shaking. You click the same way. The requester sees `accepted`. The verifier's verdict is `duress`; the customer's system decides what to do with that.
6. **The wrong hand.** Someone else uses the mouse. They get a plain "unavailable", try again, and never pass; after a few tries the member locks.
7. **The language.** Show the model's verdict for the calm and the coerced sensor windows side by side: each reading alone means nothing, together they say duress.
8. **The "it can't be read" moment.** Put the two envelopes next to each other: same shape, same size, nothing to tell them apart.

## 7. If something goes wrong

- **Tests fail after you edit `yuseal_mcu.h`:** the C++ and Python must agree byte for byte. Change both, rerun `python3 -m unittest test_yuseal`.
- **`arm_approval` keeps returning `0`:** there was no click in the last 1.5 s, the palm wasn't on the grip (touch sensor), the same click was already used, or the arm rate limit (10 per 10 minutes) was hit.
- **The verifier rejects with "no valid tag":** the verifier's tag key doesn't match the one in `secrets.h`. Re-run `provision.py`, reflash, and re-enrol.
- **The verifier rejects with "unknown or reused nonce" or "expired":** more than 2 minutes passed, the nonce was already used, or the verifier's state file was lost.
- **Duress shows up when it shouldn't:** check the veto first (a sensor may be unplugged), then the model's score. A false alarm costs a delay, never a loss, so leave the fail-closed rule alone.

See [TESTING.md](TESTING.md) for the full test steps.

## Bring-up sketches

Upload these one at a time in App Lab or the Arduino IDE (folder `app/bringup/`), before the full sketch. Each file's top comment says what PASS looks like.

| Folder | Proves | Answers |
|---|---|---|
| `step1_click` | The read-only click tap and the grip sensor | Is the switch line idle-HIGH, and does the mouse still work? |
| `step2_qwiic` | Thermo, Movement, Buttons | Is the Qwiic port `Wire1` or `Wire`? (`USE_WIRE1` switch) |
| `step3_dfrobot` | Touch and moisture pins | Are the pins and 3.3 V wiring right? |
| `step4_core` | The trusted core, no Linux | Does a click with a palm arm and seal once, and a click without refuse? |

Resolved by reading the docs: `provide_safe` is required (handlers run off the main loop); use `Monitor`, not `Serial`; the Buttons calls (`update`, `isPressed`) are right. Still to confirm on the board: String arguments over Bridge.

## Mouse mode (target design): what to build

The repo's code is **mouse mode** (built 2026-11-15; tested on a laptop, not yet on the board). The table shows what is done and what is left. Design: [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md), [OWNER-CHECK.md](OWNER-CHECK.md), [BASELINE.md](BASELINE.md).

| Order | What | Where | Test |
|---|---|---|---|
| 1 | Read-only tap on the donor mouse's left switch; STM32 timestamps each click and records whether the palm is on the grip | hardware, `sketch.ino` | Mouse-test page: every click is logged, the mouse still works |
| 2 | `arm(digest)` with the click-age rule, an arming rate limit, and the new tag `HMAC(K_TAG, "YS3/tag" \| status \| digest \| click_age \| grip \| feature hash)` | `yuseal_mcu.h`, `yuseal.py`  | C++ and Python tags match; no click means no salt; an old click is refused |
| 3 | Per-minute features on the STM32 (click, movement, grip, body), quiet windows only, MAC-attested | `sketch.ino` | A tampered feature fails the tag check |
| 4 | YubiKey **without a touch** (CTAP2 `up=false`) | `yubikey_auth.py` | **Unverified on our key.** If refused, keep touch for step-up only |
| 5 | Verifier: per-hour baseline; owner distance, three bands and continuity; quiet rejection; repeat lock and alert | `yuseal.py` | A second person gets "uncertain" or "not the owner"; the owner passes; an impostor gets identical failures |
| 6 | **Measure the owner check** with two or three people on the same mouse | dashboard | Real separation numbers; if poor, keep the owner check advisory |
| 7 | Tests for piggybacking, replay, forged tags, wrong key, swapped request | `test_yuseal.py` | All pass |

**Done in code and tests:** row 2, the owner check logic in row 5, and row 7. **Left:** rows 1, 3 (on the board), 4 and 6. Test steps: [TESTING.md](TESTING.md).
