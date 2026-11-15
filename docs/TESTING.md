# How to test YuDuino

Three levels. Do them in order. Level 1 needs only a laptop. YuDuino is a zero-input mouse: nobody types or presses anything but the mouse's own click, so there is no PIN to choose.

## Tonight's flash-and-test checklist (about 45 minutes)

Do these in order. Stop at the first failure and tell us the message.

**A. Laptop (guardian side)**
1. `git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-` then `python3 -m venv .venv && source .venv/bin/activate && pip install -r app/python/requirements.txt`
2. `cd app/python && python3 -m unittest test_yuseal` must say `OK` (58 tests). Then `cd ../..`.
3. `python3 tools/provision.py` makes `app/sketch/secrets.h` (the STM32's secret) and `tools/out/guardian_tag_key.json`.
4. `cp .env.example .env`, set `GEMINI_API_KEY`, `GEMINI_MODEL`, and `ADDRESS_BOOK='{"0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3":"ALICE"}'`. Start the guardian: `cd app/python && set -a && source ../../.env && set +a && uvicorn guardian:app --host 0.0.0.0 --port 8000`. Leave it running; it prints every outcome.

**B. Flash the STM32**
5. Copy `app/sketch/` (including the new `secrets.h`) into the App Lab sensor app's `sketch/` folder and put `app/dashboard/applab_relay.py` in as its `python/main.py` (it now also carries the approval calls). Start the app.
6. Click test: upload `app/bringup/step1_click` first if the mouse tap is wired (monitor prints DOWN/UP and `grip=`). **No donor mouse tonight?** In `sketch.ino` uncomment `#define CLICK_FROM_MODULINO_BUTTON` and use button A as the click; hold the touch pad as the palm.
7. On the board, check the relay is up: `ls ~/ArduinoApps/durhack-sensors/live/` shows `features.json` and an `rpc/` folder. If `rpc/` is missing, the old relay is still running: restart the app.

**C. Board (Linux side)**
8. `cd ~/Durhack- && git pull && source ~/durhack-venv/bin/activate && pip install -r app/python/requirements.txt`. Copy the laptop's `.env` and `tools/out/` to the board (`scp -r tools/out jonah@<board>:~/Durhack-/tools/`).
9. **Probe the YubiKey first:** `python3 tools/yk_probe.py` (touch the key once when asked). It prints which mode to use:
   - `fido`: nothing more to do.
   - `hmac-sha1`: `pip install yubikey-manager && python3 tools/setup_yk_hmac.py`, then add `--yk hmac-sha1` to every `main.py` command below.
   - `fido-touch` only: works, but needs a tap per approval (not zero input). Use `--yk fido-touch` for a demo and tell us.
10. Start the dashboard if you want the camera: `app/dashboard/restart.sh` (approvals take their camera frame from it, because the camera can't be opened twice).

**D. End to end**
11. Enrol (click the mouse once when asked): `python3 app/python/main.py enrol jonah`. Expect `{'ok': True}`.
12. Approve (then click within 5 seconds): `python3 app/python/main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"}'`. Expect `Requester is told: accepted`; the guardian prints `execute` (or `hold_and_alert` if Gemini says duress, which is also correct behaviour).
13. No click: run step 12 and do not click. Expect `Refused: no real click ...` after 5 seconds and nothing in the guardian.
14. Wrong hand: after about 20 normal approvals the baseline exists; have a teammate use the mouse. Expect `unavailable` for them and an `ALERT` in the guardian after three tries.

If a Bridge call fails with an argument error, tell us: the fix is in `docs/BUILD-FLOW.md` section 5, item 1.

## Level 1: laptop, no hardware (2 minutes)

```bash
git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-/app/python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt fastapi httpx   # needs cryptography>=48
python3 -m unittest test_yuseal -v               # expect: Ran 58 tests ... OK
```

Needs `g++` too: some tests compile the real STM32 code (`app/sketch/yuseal_mcu.h`) and check it matches the Python version byte for byte.

**What a pass proves:** the three proofs verify; no click, a click with no palm on the grip, an old click, a second arm from one click, or too many arms are all refused by the STM32 core; a changed request, a replayed nonce, a forged or swapped tag, a doctored sensor summary or a back-dated click are rejected by the guardian; a stranger's hand gets the same plain "unavailable" as any other failure and is locked out after repeats, while the owner's hand passes; a learning period never rejects anyone; only passed, normal approvals teach the baseline; a duress approval looks identical from outside but is held inside; the audit log detects tampering; the whole Linux flow works against a fake board.

## Level 2: board bring-up (about 30 minutes, needs the UNO Q)

Upload each sketch from `app/bringup/` and watch the serial monitor. Each file's top comment says what PASS looks like.

1. `step1_click`: with a read-only tap from the donor mouse's left-button switch to the click pin, the monitor prints DOWN and UP with the hold time when you click, `grip=1` with your palm on the mouse, and the mouse still works normally.
2. `step2_qwiic`: temperature and accel values print; buttons print A/B/C (the Modulino Buttons are only a bench stand-in for the click). If nothing is found, flip `USE_WIRE1` and re-upload. **Tell us which value worked.**
3. `step3_dfrobot`: touch is 1 only while touched; moisture rises with a damp finger.
4. `step4_core`: needs `secrets.h` first (`python3 tools/provision.py`). Click with your palm on the mouse: it prints `armed` then `sealed ...` once per click. A click with no palm on the grip prints `refused`.

## Level 3: full flow on the board

1. Flash `app/sketch/sketch.ino` (with `secrets.h` from the step above). No donor mouse yet? Uncomment `CLICK_FROM_MODULINO_BUTTON` and use button A as the click.
2. Plug the YubiKey into the hub. Start the guardian on the laptop: `cd app/python && uvicorn guardian:app --port 8000`.
3. Copy `.env.example` to `.env`; set `GUARDIAN_URL` and the same `ADDRESS_BOOK` (JSON, address -> unique name) for the guardian and the board, then on the board: `python3 main.py enrol alex` and click once (that supervised click seeds the baseline).
4. `python3 main.py approve alex '{"action":"transfer","to":"<address in address book>","amount":"10","asset":"GBP"}'` then click within a few seconds.
   - **Owner's hand, calm** -> the requester is told `accepted`; the guardian prints `execute`.
   - **Shaky hand or a second face in the camera** -> still `accepted` outside; the guardian prints `hold_and_alert`.
   - **Someone else on the mouse** (after the guardian has some baseline) -> `unavailable`, and after repeats a lock and an alert.
   - **No click** -> nothing is signed; the command times out.
   - **Click with no palm on the grip** -> nothing is signed.
   - **A request to an address not in the book** -> refused.

## Known unverified (please report what you see)

The click tap and its polarity; Bridge String arguments; Wire vs Wire1; and above all whether the YubiKey 5 gives its hmac-secret **without a touch** (`up=false`) through `RealYubiKey` (fallbacks in `docs/BUILD-FLOW.md` section 5). If the key insists on a touch, tell us: it changes the design.
