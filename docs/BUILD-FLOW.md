# YuDuino build flow: hardware and code together

*Written 14 November 2026, evening of day one of DurHack.* This page answers one question: **for each piece of hardware, what do I code, in which file, in which language, on which chip, and how do I know it works?** Back to the **[crypto design](CRYPTO.md)** · **[hardware plan](HARDWARE-PLAN.md)** (wiring) · **[dev plan](DEV-PLAN.md)** (the waves).

## 1. The map: three computers, one rule

```
┌──────────────────────────── Arduino UNO Q ─────────────────────────────┐
│                                                                        │
│  STM32U585 (C++, app/sketch/)              Linux, QRB2210 (Python, app/python/)
│  ───────────────────────────               ─────────────────────────────────────
│  yuseal_mcu.h  trusted core                main.py      entry: enrol / approve
│  sketch.ino    glue: buttons, sensors,     approve.py   one approval, step by step
│                LED matrix, Bridge calls    yuseal.py    envelope + crypto
│       ▲                                    yubikey_auth.py  YubiKey over USB
│       │ Bridge (remote calls)              camera.py, fusion_gemini.py  Gemini
│       └────────────────────────────────────────┘
│  owns: Modulino Buttons, Movement,       owns: USB hub → YubiKey + camera + mic,
│        Thermo, touch D2, moisture A0,           Wi-Fi → Gemini + guardian
│        LED matrix, PIN, tag key
└────────────────────────────────────────────────────────────────────────┘
                                   │ HTTPS
                                   ▼
        guardian.py (Python, FastAPI) on a Vultr server: the verifier. Laptop in Wave 1.
```

**The one rule:** the PIN, the LED text and the status (normal / second approver / duress) are handled **only by the STM32**. Linux asks it questions and relays answers, but never sees a button press. If you ever write code that reads the PIN on Linux, or decides the duress status on Linux, you have broken the design. (That is exactly what the old `main.py` did; it has been replaced.)

## 2. What to code where, file by file

| File | Chip and language | Job | State |
|---|---|---|---|
| `app/sketch/yuseal_mcu.h` | STM32, C++ | The trusted core: SHA-256, HMAC, PIN check, lockout, status rule, tag | **Done and tested** on a laptop against Python. Don't edit unless you also change `yuseal.py` and `test_yuseal.py` |
| `app/sketch/sketch.ino` | STM32, C++ | Glue: reads buttons and sensors, calls the core, shows text, exposes Bridge calls | Written, **not yet run on the board**. Four `VERIFY` marks (below) |
| `tools/provision.py` | Laptop, Python | Makes the STM32's secrets (`secrets.h`) and the guardian's tag key | Done and runs |
| `app/python/yuseal.py` | Linux and guardian, Python | The envelope, display rules, checks, key store, audit log | **Done and tested** |
| `app/python/approve.py` | Linux, Python | The step-by-step flow of one approval and of enrolment | Done, tested with a fake STM32 and YubiKey |
| `app/python/guardian.py` | Vultr (or laptop), Python | The verifier: nonce, enrolment, `/approve` | Done, tested with FastAPI's test client. Alerts and incident reports are your Wave 3 work |
| `app/python/yubikey_auth.py` | Linux, Python | `RealYubiKey`: the real YubiKey over USB | Written, **not yet run on hardware** |
| `app/python/main.py` | Linux, Python | `enrol` and `approve` commands, wires everything together | Written, not run on hardware |
| `app/python/fusion_gemini.py`, `camera.py` | Linux, Python | Gemini call, camera frame (as before) | Existing code. `gemini_fn` in `main.py` calls them |

**Your actual coding work** is therefore small and concentrated. In order:

1. Make the four `VERIFY` items in `sketch.ino` work on the real board (§5).
2. Make `RealYubiKey` work on the real YubiKey (§5).
3. Wave 2: feed real sensor windows to Gemini (`gemini_fn`) and tune the onboard veto limits (`onboard_veto` in `approve.py`).
4. Wave 3: alerts, incident reports, dashboard and Tiger Data in `guardian.py` (`on_outcome` is the hook); HTTPS and pinning.
5. Wave 4: readout protection, SLH-DSA root, Solana.

You never have to write cryptography, only call it.

## 3. The flow, wave by wave: hardware step, code step, test

Each row is one sitting. Don't move on until the **Test** passes. All commands run from the repository root unless stated.

### Before the board: check the code on your laptop (10 minutes, do this first)

```bash
pip install -r app/python/requirements.txt fastapi httpx
cd app/python && python3 -m unittest test_yuseal -v
```

**Test:** 41 tests pass. (The C++ tests need `g++`; they're skipped without it.) If this fails on your laptop, stop and fix it before touching hardware.

### Wave 1: skeleton (19:30 to 23:30)

| # | Hardware step ([hardware plan](HARDWARE-PLAN.md)) | Code step | Test |
|---|---|---|---|
| 1 | **Step 0 to 1:** power, hub, board on Wi-Fi, LED matrix scrolls text | In App Lab, find the LED matrix text example. Put its scrolling call inside `showText()` in `sketch.ino` | `showText("PAY 10 GBP TO ALICE")` scrolls readably |
| 2 | **Step 2:** Qwiic chain: Thermo, Movement, Buttons | Check `Modulino.begin()` and the Buttons calls in `loop()` (`update()`, `isPressed(i)`) | Pressing A, B, C prints each; holding a button shows the held state |
| 3 | **Step 3:** touch on D2, moisture on A0 | Nothing new; `digitalRead(TOUCH_PIN)` is already the grip check | Touch pad reads 1 when held |
| 4 | *(laptop)* | `python3 tools/provision.py --pin ABCABCAB --duress-pin ABCABCAb` | Prints "Wrote app/sketch/secrets.h…" |
| 5 | Flash `sketch.ino` (with the new `secrets.h`) from App Lab | Check that `Bridge.provide()` accepts the three approval handlers with String arguments (§5, item 1) | From the Linux side, `Bridge.call("get_features")` returns JSON with `state` and `pin_count` |
| 6 | *(laptop or board)* | `cd app/python && uvicorn guardian:app --port 8000`, with `ADDRESS_BOOK='{"0xA1B2…":"ALICE"}'` in the environment | `curl -X POST localhost:8000/nonce` returns a nonce |
| 7 | **Step 6, basic route:** YubiKey plugged into the hub | Make `RealYubiKey` work (§5, item 4). Run `python3 main.py enrol jonah` and follow the prompts: enter the **normal** PIN on the buttons, touch the YubiKey | Prints `{'ok': True}` |
| 8 | **Milestone 1** | `python3 main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2…"}'` | LED shows `PAY 10 GBP TO ALICE`; enter the normal PIN while holding the grip; touch; LED shows `OK`; the guardian prints `execute` |
| 9 | | Repeat with the **duress PIN** (same presses, last one held) | LED shows the same `OK`; the requester is told `accepted`; the guardian prints `hold_and_alert` and `SILENT ALERT` |
| 10 | | Unplug the Wi-Fi from the board (or unset `GEMINI_API_KEY`) and approve with the normal PIN | The guardian prints `hold_and_alert`: no verdict means duress |

**Done when** rows 8, 9 and 10 pass. That is the Wave 1 demo, and it's the whole core idea: calm approves, coerced and "no Gemini" both hold, and from outside they look identical. Commit and tag `wave-1`.

### Wave 2: real signals (23:30 to 03:30)

| Hardware step | Code step | Test |
|---|---|---|
| Sensors into the cardboard grip; tape every joint | None | A loose wire mid-demo trips the veto; tape it |
| One-minute calm baseline | In `main.py enrol`, record `capture_window(30)`-style readings into `device.json`; send to Tiger Data | Baseline row appears in Tiger Data |
| Camera and microphone on the hub | `gemini_fn` in `main.py` already grabs a frame; add the mic features to the summary | `gemini_fn` returns `duress_score` for a calm and a shaky approval |
| Calm vs. shaking approvals | Put each reading as a **delta from the baseline** in `gemini_fn`'s summary | Calm gives a low score, shaking and a second face give a high one, with reasons |
| | Tune the limits in `onboard_veto` (`approve.py`) to your real sensors | An unplugged Thermo triggers `veto` |
| | Try to persist the lockout counter in the STM32's flash (VERIFY, §5, item 5). If it can't, say so in the write-up | After 5 wrong PINs and a power cycle, the device is still locked |

**Done when** the same person approving calmly and then shaking gets different verdicts with sensible reasons, and replaying an old envelope is rejected (`curl` the same `/approve` body twice). Tag `wave-2`.

### Wave 3: response and polish (03:30 to 07:30)

| Hardware step | Code step | Test |
|---|---|---|
| 3D-printed grip and enclosure; YubiKey dock | None | The device works fully assembled |
| | Deploy `guardian.py` to Vultr behind HTTPS (Caddy or nginx). Pin its certificate in `main.py`'s `requests` call | Approval works over the internet; a wrong certificate is refused |
| | In `guardian.on_outcome`: send the Telegram or email alert, write the incident report with Gemini, freeze funds, store to Tiger Data | A duress approval fires an alert and a report appears on the dashboard |
| | Make the guardian the only route to "execute" (the wallet or demo contract only accepts calls from it) | Nothing executes without a guardian `execute` |
| | Optional: YubiKey attestation at enrolment (`attestation="direct"`) | A software "YubiKey" can't enrol |
| | ElevenLabs reads **only the request text** aloud | Same speech for normal and duress |

**Done when** a coerced approval looks normal on the device and, within seconds, a phone gets an alert and the dashboard shows an incident report and frozen funds. Tag `wave-3`.

### Wave 4: harden and stretch (07:30 to 10:30)

| Hardware step | Code step | Test |
|---|---|---|
| Privacy hood over the buttons; spare cables | Lock the STM32's debug port and enable readout protection if the toolchain allows | Flash can't be read through the debug port |
| | Check `openssl version` is 3.5+ on the board; test that TLS to the guardian negotiates `X25519MLKEM768` | `openssl s_client -groups X25519MLKEM768 …` succeeds |
| | Rehearse the Binance-replay demo twice; record a backup video | Runs start to finish without touching a laptop, twice |
| | Stretch: Solana devnet program checks the envelope and releases or freezes funds | A normal approval releases, a duress approval freezes on chain |

## 4. Who codes what

The same four roles as the [dev plan](DEV-PLAN.md#who-does-what-team-of-4), now with files:

| Role | Files | First job |
|---|---|---|
| **1. Microcontroller and sensors** | `sketch.ino` (and `yuseal_mcu.h` only with someone else reviewing) | Rows 1 to 5 of Wave 1: matrix, Qwiic, Bridge calls |
| **2. Linux side and Gemini** | `main.py`, `approve.py` (`gemini_fn`, `onboard_veto`), `camera.py`, `fusion_gemini.py`, `yubikey_auth.py` | Row 7: `RealYubiKey` on the real key; then `gemini_fn` |
| **3. Crypto and backend** | `guardian.py`, `yuseal.py`, `tools/provision.py`, Vultr, Tiger Data | Rows 4 and 6; then Wave 3's alerts and dashboard |
| **4. Build and pitch** | grip, enclosure, dashboard look, demo script, video | Print the grip; write the demo script from §6 |

**Review rule:** any change to `yuseal_mcu.h`, `yuseal.py` or the tag format needs the tests to pass and a second person to read it. Everything else can move fast.

## 5. Things we couldn't check without the board, and what to do if they fail

| # | Unverified | Where | If it doesn't work |
|---|---|---|---|
| 1 | `Bridge.provide()` accepts handlers with **String arguments** and `Bridge.call(name, a, b)` passes them | `sketch.ino`, `main.py` (`_Bridge`) | Pack the arguments into one String (`"text\|digest"`), split it in the sketch, and change `_Bridge.call` to join them |
| 2 | The **LED matrix text** call | `showText()` | Scroll with the matrix library's frame API, or use a plain 8-character abbreviation. The requirement is only that it shows the same text that `begin_approval` was given |
| 3 | The **Buttons** API (`update()`, `isPressed(i)`) | `loop()` | Use the library's press and release callbacks and call `core.buttonDown('A'+i, grip, millis())` and `core.buttonUp(millis())` from them |
| 4 | **`RealYubiKey`**: python-fido2 returning the raw authenticator data, client data and signature, with our challenge; USB access to `/dev/hidraw*` from inside App Lab | `yubikey_auth.py` | Run `main.py` as a normal process over SSH, not inside the App Lab container, with a udev rule for Yubico. **Fallback:** keep the YubiKey in the laptop and run a 30-line relay there that exposes the same two methods (`register`, `assert_and_secret`) behind an SSH tunnel; `approve.py` doesn't care |
| 5 | **Persistent storage** on the STM32 (for the lockout counter) | not written yet | Keep the counter in RAM (already so); say in the write-up that power-cycling resets it, and rely on the guardian counting attempts |
| 6 | `millis()` is monotonic and doesn't wrap during an approval | `yuseal_mcu.h` | It wraps after about 50 days; reboot before the demo |
| 7 | The board has **no hardware random number generator exposed to the sketch** | not needed | The design needs no randomness on the STM32: all its secrets come from `provision.py` |

The first time any of these runs, tell the team and tick it off in [PLAN.md](PLAN.md#things-to-verify-in-hour-02-not-yet-tested-on-hardware).

## 6. The demo, in order

1. **The Binance replay.** On the laptop, an attack script posts a transfer straight to the signing service. The guardian refuses it: no envelope, no execution.
2. **The legitimate request.** The script asks the guardian properly. The LED matrix scrolls `PAY 10 GBP TO ALICE`. Hold the grip, enter the PIN, tap the YubiKey. `OK`. The guardian executes.
3. **The swap.** Change the destination after approval. The guardian rejects it (request hash).
4. **The replay.** Send the same envelope again. Rejected (nonce used).
5. **The coerced approval.** A teammate stands behind you, hand on your shoulder. You enter the duress PIN (same buttons, one press longer). The LED shows the same `OK`. The requester sees `accepted`. The funds don't move; a phone buzzes; the dashboard shows the incident, Gemini's explanation and the frozen funds.
6. **The language.** Show the Gemini verdict for the calm and the coerced sensor windows side by side: each reading alone means nothing, together they say duress.
7. **The "it can't be read" moment.** Put the two envelopes next to each other: same shape, same size, nothing to tell them apart.

## 7. If something goes wrong

- **Tests fail after you edit `yuseal_mcu.h`:** the C++ and Python must agree byte for byte. Change both, rerun `python3 -m unittest test_yuseal`.
- **`begin_approval` returns `0`:** the text was over 96 characters, had non-printable characters, or the STM32 is locked. Power-cycle.
- **PIN never completes:** the grip isn't held (touch sensor), or the PIN has the wrong length. The device needs exactly the number of presses `provision.py` was given.
- **Guardian rejects with "no valid tag":** the guardian's tag key doesn't match the one in `secrets.h`. Re-run `provision.py`, reflash, and re-enrol.
- **Guardian rejects with "unknown or reused nonce" or "expired":** more than 2 minutes passed, or the guardian restarted (its nonces and members are in memory in Wave 1). Re-enrol after a restart.
- **Duress shows up when it shouldn't:** check the veto first (a sensor may be unplugged), then Gemini's reasons. A false alarm costs a delay, never a loss, so leave the fail-closed rule alone.

See [TESTING.md](TESTING.md) for the full test steps.

## Bring-up sketches

Upload these one at a time in App Lab or the Arduino IDE (folder `app/bringup/`), before the full sketch. Each file's top comment says what PASS looks like.

| Folder | Proves | Answers |
|---|---|---|
| `step1_matrix` | LED matrix text | Does `ArduinoGraphics` + `Arduino_LED_Matrix` draw text? |
| `step2_qwiic` | Thermo, Movement, Buttons | Is the Qwiic port `Wire1` or `Wire`? (`USE_WIRE1` switch) |
| `step3_dfrobot` | Touch and moisture pins | Are the pins and 3.3 V wiring right? |
| `step4_buttons` | The trusted PIN core, no Linux | Do press/hold timing and the grip gate work? |

Resolved by reading the docs: `provide_safe` is required (handlers run off the main loop); use `Monitor`, not `Serial`; the Buttons calls (`update`, `isPressed`) are right. Still to confirm on the board: String arguments over Bridge, and whether matrix text flickers at the 120 ms redraw.
