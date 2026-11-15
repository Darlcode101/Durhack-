# How to test YuDuino

Three levels. Do them in order. Level 1 needs only a laptop. YuDuino is a zero-input mouse: nobody types or presses anything but the mouse's own click, so there is no PIN to choose.

## Level 1: laptop, no hardware (2 minutes)

```bash
git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-/app/python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt fastapi httpx   # needs cryptography>=48
python3 -m unittest test_yuseal -v               # expect: Ran 54 tests ... OK
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
