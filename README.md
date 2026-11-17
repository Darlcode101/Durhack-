# YuDuino

A transaction approver hidden inside a computer mouse. You use it like a normal mouse all day, and when you click "process transaction" it quietly checks two things: that the hand on the mouse is yours, and that you aren't being forced. Nothing to type, no PIN, no screen.

We built it at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC, and it came 2nd in the RS / Arduino track. Our slides are in [presentation/](presentation/YuDuino-DurHack-2026-pitch.pdf).

## Why we built it

On 29 October 2026 about $6.34 billion was taken from Binance hot wallets. The attackers got in through compromised engineer laptops, found a deploy token, and drove the signing service directly. No person was ever asked to approve anything.

Hardware keys fix part of that, but even the best encryption doesn't help when someone is standing at your desk telling you to click. So we wanted an approval that needs a real hand on a real device, and that can tell when that hand is under stress, without the attacker noticing anything is being checked.

## How it works

The UNO Q, a few sensors and the mouse's own click switch all sit inside the mouse. A small dock behind the monitor holds the USB-C hub, the YubiKey and a camera.

While you use the mouse, the STM32 side of the board reads grip, tremor, palm temperature, humidity and sweat, but only while your palm is actually on it. It keeps a rolling average and spread for each sensor for each hour of the day, so it learns what your normal looks like at 9am versus 11pm. Everyday use is only learned from. Nothing gets judged until you make a transaction.

When you click "process transaction":

1. The customer's system sends a request with a one-time nonce.
2. The STM32 sees the physical click through a read-only tap on the mouse switch. Linux has 1.5 seconds after that click to arm the STM32 with the request. No click, no palm on the grip, or a reused click means nothing happens.
3. The STM32 releases a salt that lets the YubiKey (no touch needed) unlock the post-quantum signing key.
4. Your last minute of sensor readings is compared with your baseline for that hour and scored by a small anomaly model running on the board.
5. The STM32 turns the score into a status (normal, step-up or duress) and seals it into a tag along with the request, the click and a hash of the sensor summary.
6. The customer's verifier checks everything and decides what to do.

Under duress the requester still sees "accepted" and the envelope looks exactly the same. Only the verifier can read the hidden status, so the customer's system can hold the transfer and raise a silent alarm. If a different person is using the mouse, the verifier's owner check spots that their hand doesn't match and they get a plain "unavailable", the same as any other failure. They can keep trying but never get through, and after three of those in ten minutes the verifier locks that user.

If anything is missing or broken (no model, a bad score, a sensor unplugged) it fails closed and counts as duress.

More detail: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

## The duress model

We started out using Gemini and a cloud database, then moved everything onto the board. Nothing leaves the device.

The model is a K-means anomaly detector trained in Edge Impulse on 2000 rows of synthetic calm data, with 17 inputs. Most of the inputs are z-scores, (x − μ) / σ, against your own mean for that hour, so one generic model ends up personal to each user without being retrained on their data. Your profile and the model are stored on the board encrypted with AES-256-GCM, under a key only the STM32 can derive.

Two edge cases we had to handle:

- People walking past or a coworker nearby shouldn't count. The camera only flags someone standing close and facing the screen for 3 seconds or more.
- If you've just come back from a run, your sweat and shake will be high. After 5+ minutes away from the mouse, readings that are high but falling are treated as recovery and can't trigger duress on their own.

More detail: [docs/EDGE-IMPULSE.md](docs/EDGE-IMPULSE.md).

## YuSeal (the crypto)

Every approval is an envelope with three separate proofs:

| Proof | Made by |
|---|---|
| ES256 signature over the request | the YubiKey |
| HMAC-SHA-256 tag over the status, request, click and sensor summary | the STM32 |
| ML-DSA-65 post-quantum signature over all of it | the Linux side, with a key the YubiKey and STM32 unlock together |

Each envelope also links to the previous one, so the audit log is a hash chain and any edit shows. Getting two of the three proofs still isn't enough to approve something. Full write-up in [docs/CRYPTO.md](docs/CRYPTO.md).

## Hardware

| Part | What it does |
|---|---|
| Arduino UNO Q | STM32 side: click, sensors, baseline, final decision and tag. Linux side: YubiKey, ML-DSA key, model |
| YubiKey 5 NFC | proves who is approving |
| Modulino Movement | tremor and movement |
| Modulino Thermo | palm temperature and humidity |
| DFRobot touch sensor | is a palm actually on the mouse |
| DFRobot moisture sensor | second sweat and contact signal |
| Arduino USB camera | the over-the-shoulder rule (frames stay in memory) |
| Arduino USB-C hub and power supply | power, YubiKey and camera on the UNO Q's single USB-C port |

Wiring and bring-up: [docs/HARDWARE.md](docs/HARDWARE.md).

## Trying it

You can run the whole thing on a laptop without any hardware. You need Python 3.10+ and `g++` (some tests compile the real STM32 code and check it matches the Python byte for byte).

```bash
git clone https://github.com/Darlcode101/Durhack-.git && cd Durhack-
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/python/requirements.txt
cd app/python && python3 -m unittest test_yuseal -v    # 75 tests
```

`cryptography` 48 or newer has ML-DSA built in, so there's no liboqs to build. Setting it up on the board, step by step: [docs/TESTING.md](docs/TESTING.md).

## Code

```
app/sketch/        STM32 sketch: click tap, sensors, per-hour baseline (baseline_mcu.h), trusted core (yuseal_mcu.h)
app/bringup/       one small test sketch per hardware step
app/python/        Linux side: main.py (enrol, approve, learn, seed, import-model), yuseal.py (envelope,
                   verifier, owner check, audit log), edge_model.py, userprofile.py, verify_cli.py, tests
app/dashboard/     live dashboard for the demo, with a local SQLite store on the board
tools/             provision.py (makes the STM32's secrets), training data generator, YubiKey helpers
presentation/      the DurHack slides
```

## Status

The crypto, the STM32 core, the owner check and the Linux flow all pass 75 tests on a laptop. On the board we've confirmed the YuSeal tests, the Modulino sensors, the YubiKey over the hub, the camera, the Bridge link and the live dashboard. Things we haven't run on the board yet: the Edge Impulse model and encrypted profile, the STM32 baseline, the full mouse-mode sketch, the YubiKey without a touch, and enrol/approve end to end. [docs/TESTING.md](docs/TESTING.md) lists them with fallbacks.

## Limits

There is no screen, so malware on the laptop could show you one transfer and send another. The verifier binds the exact request, but you can't see it on the mouse. Stress isn't always duress, and the owner check is statistical, so it will sometimes turn away the real owner. We haven't measured its error rates. The UNO Q also has no certified secure element.

## Team

Jonah and Alex, DurHack 2026.
