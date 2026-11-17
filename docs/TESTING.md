# Setting it up and testing it

Back to the [README](../README.md). Do these in order and stop at the first thing that fails.

## 1. On a laptop, no hardware

```bash
git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/python/requirements.txt
cd app/python && python3 -m unittest test_yuseal -v    # Ran 75 tests ... OK
```

You need `g++` too. Some tests compile the real STM32 code (`app/sketch/yuseal_mcu.h`) and check it gives the same bytes as the Python version.

A pass means: the three proofs verify; the STM32 core refuses no click, no palm, an old click, a second arm from one click and too many arms; the verifier rejects a changed request, a reused nonce, a forged or swapped tag, a doctored sensor summary and a back-dated click; a stranger's hand gets the same "unavailable" as any other failure and gets locked out after repeats, while the owner passes; a duress approval looks identical from outside; and editing the audit log is caught.

## 2. Flash the board

1. Install Arduino App Lab on your laptop, update the UNO Q, and put it on Wi-Fi (a phone hotspot is easiest, venue Wi-Fi with a sign-in page won't work).
2. On the laptop, run `python3 tools/provision.py`. It writes `app/sketch/secrets.h` (the STM32's secret) and `tools/out/` (the verifier's copy of the tag key). Both are gitignored.
3. In App Lab, make an app, copy `app/sketch/` (with `secrets.h`) into its `sketch/` folder, put `app/dashboard/applab_relay.py` in as its `python/main.py`, and start it.
4. Check `~/ArduinoApps/<app>/live/` on the board has `features.json` and an `rpc/` folder.

Wiring and the bring-up sketches are in [HARDWARE.md](HARDWARE.md).

## 3. Set up the Linux side

1. On the board: clone the repo, make a venv and `pip install -r app/python/requirements.txt`. Copy `tools/out/` over from the laptop.
2. Let your user reach the YubiKey (`/dev/hidraw*`) with a udev rule for Yubico devices.
3. Run `python3 tools/yk_probe.py` and touch the key once when asked. It tells you which mode works:
   - `fido`: nothing more to do, no touch needed.
   - `hmac-sha1`: run `pip install yubikey-manager && python3 tools/setup_yk_hmac.py`, then add `--yk hmac-sha1` to every `main.py` command.
   - `fido-touch` only: it works, but needs a tap per approval.
4. `cp .env.example .env`, fill in `PROFILE_DIR` and `EI_ANOMALY_LIMIT`, and install the model with `python3 app/python/main.py import-model <user> generic.eim` ([EDGE-IMPULSE.md](EDGE-IMPULSE.md)).
5. Seed a baseline: `python3 app/python/main.py seed <user> 15` with a hand on the mouse.

## 4. End to end

The reference verifier (`verify_cli.py`) stands in for the customer's system and runs on the laptop.

```bash
# board: enrol, click once when asked
python3 app/python/main.py enrol jonah > package.json
# laptop
python3 app/python/verify_cli.py enrol jonah package.json
N=$(python3 app/python/verify_cli.py nonce)
# board: approve, then click within a few seconds
python3 app/python/main.py approve jonah '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"}' --nonce "$N" > envelope.json
# laptop (save the same request as request.json)
python3 app/python/verify_cli.py check envelope.json request.json
```

What you should see:

- owner, calm: `"public": "accepted"`, `"verdict": "normal"`
- owner, shaky or with someone close behind: still `accepted` outside, but `"verdict": "duress"`
- someone else on the mouse (once there's a baseline): `unavailable`, and locked after three tries
- no click, or a click with no palm on the grip: nothing gets signed

## 5. The live dashboard

The dashboard shows the verdict live, with the camera, each signal against your normal, the model's score and history from the local store. Start it on the board with `app/dashboard/restart.sh` and open `http://<board-ip>:8080`. History is kept in a SQLite file on the board (`STORE_PATH`, default `app/dashboard/data/yuduino.db`). Only derived numbers are stored, never frames or keys.

## Not yet tested on the board

| What | If it doesn't work |
|---|---|
| The YubiKey giving its `hmac-secret` without a touch | use the `hmac-sha1` mode above (weaker, because the verifier holds the slot key), or `fido-touch` |
| Bridge passing String arguments | pack the arguments into one String and split it in the sketch |
| The click tap's polarity | swap it in the sketch, or use `CLICK_FROM_MODULINO_BUTTON` on the bench |
| The Edge Impulse model, the encrypted profile and the STM32 baseline on the board | with no model the dashboard's body score decides, then it fails closed |
| `enrol` and `approve` end to end, and the touch and moisture sensors in the mouse | |

The arm rate limit is kept in RAM, so a power cycle resets it. The verifier's lock after repeated failures covers that.
