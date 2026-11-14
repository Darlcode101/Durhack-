# How to test YuDuino

Three levels. Do them in order. Level 1 needs only a laptop.

## Level 1: laptop, no hardware (2 minutes)

```bash
git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-/app/python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # needs cryptography>=48
python3 -m unittest test_yuseal -v       # expect: Ran 38 tests ... OK
```

Needs `g++` too: one test compiles the real STM32 code (`app/sketch/yuseal_mcu.h`) and checks it matches the Python version byte for byte.

**What a pass proves:** the three proofs verify; a wrong PIN, a changed request, a swapped display text, a replayed nonce or a forged tag are all rejected; the duress PIN gives an envelope that looks identical but is read as duress by the guardian; the audit log detects tampering; the whole Linux flow works against a fake board.

## Level 2: board bring-up (about 30 minutes, needs the UNO Q)

Upload each sketch from `app/bringup/` and watch the serial monitor. Each file's top comment says what PASS looks like.

1. `step1_matrix`: "HELLO" scrolls on the LED matrix.
2. `step2_qwiic`: temperature and accel values print; buttons print A/B/C. If nothing is found, flip `USE_WIRE1` and re-upload. **Tell us which value worked.**
3. `step3_dfrobot`: touch is 1 only while touched; moisture rises with a damp finger.
4. `step4_buttons`: needs `secrets.h` first:
   ```bash
   python3 tools/provision.py --pin AAbBcC... --duress-pin AAbBcc...   # pick your own 8-12 presses
   ```
   Hold the grip and type the PIN: `state=1` while typing, `state=2` after the right one, `state=3` after 5 wrong PINs (lockout until power cycle).

## Level 3: full flow on the board

1. Flash `app/sketch/sketch.ino` (with `secrets.h` from the step above).
2. Plug the YubiKey into the hub. Start the guardian on the laptop: `cd app/python && uvicorn guardian:app --port 8000`.
3. Copy `.env.example` to `.env`; set `GUARDIAN_URL` and the same `ADDRESS_BOOK` (JSON, address -> unique name) for the guardian and the board, then on the board: `python3 main.py enrol alex` (enter the normal PIN once, touch the key).
4. `python3 main.py approve alex '{"action":"transfer","to":"<address in address book>","amount":10,"asset":"GBP"}'`
   - **Normal PIN + calm** -> the matrix shows the request, then OK; guardian prints `execute`.
   - **Duress PIN** -> the matrix still shows OK; the guardian prints `hold_and_alert`.
   - **Wrong PIN x5** -> locked until power cycle.
   - **No grip held** -> presses are ignored.
   - **A request to an address not in the book** -> refused, nothing shown.

## Known unverified (please report what you see)

Bridge String arguments; matrix flicker at the 120 ms redraw; Wire vs Wire1; `RealYubiKey` over USB (fallbacks in `docs/BUILD-FLOW.md` section 5).
