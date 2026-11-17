# How YuDuino works

Back to the [README](../README.md). The crypto is in [CRYPTO.md](CRYPTO.md) and the model in [EDGE-IMPULSE.md](EDGE-IMPULSE.md).

## The mouse

The whole device hides inside an ordinary office mouse that still works as a mouse. There's no screen and no extra buttons, and the user never types anything. The only input is the click they would make anyway on "process transaction".

The STM32 reads that click through a read-only tap on the mouse's left switch. It never drives the line, so malware on the laptop can fake a click in the OS but can't make the switch close. A touch sensor under the palm tells it whether a hand is actually on the mouse, and a click only counts if one is.

The YubiKey and a camera live in a small dock (the USB-C hub) behind the monitor. A thin USB-C cable powers the board, and the UNO Q talks to the outside over its own Wi-Fi.

## Learning your normal

People hold a mouse for hours a day, which gives us far more data than a one-off enrolment. While a palm is on the mouse, the STM32 reads humidity, moisture, shake and temperature and folds each reading into a running mean and variance for that sensor and that hour of the day (24 buckets per sensor). The count is capped at 1000 so old habits fade out slowly. An hour needs 20 samples before its numbers are used.

On the Linux side, the learner (`python3 main.py learn <user>`) turns each minute into one row of features and throws the raw samples away. It keeps the last minute in RAM for the transaction check. For a demo, `python3 main.py seed <user> 15` seeds 15 minutes.

All of this is learning only. Nothing is judged or flagged during everyday use. Duress is checked only at the moment of a transaction.

## One approval, step by step

1. The customer's system sends a request and a one-time nonce. The nonce is valid for 2 minutes on the verifier's clock.
2. The user clicks "process transaction". The STM32 timestamps the click and notes whether the palm was on the grip.
3. Linux arms the STM32 with the request digest and the sensor summary. The STM32 refuses unless there was a real click with a palm on the grip in the last 1.5 seconds. Each click arms once, and there's a limit of 10 arms per 10 minutes.
4. Once armed, the STM32 releases a salt. The YubiKey (no touch) uses it to unlock the ML-DSA key and signs the request.
5. The last minute of readings is scored against that hour's baseline by the on-device model, giving a number from 0 to 100.
6. The STM32 decides the status and makes the tag. Arm to seal has to happen within 30 seconds, and each arm gives one tag.
7. Linux signs the whole envelope with ML-DSA and adds it to the audit log.
8. The customer's verifier checks the three proofs, then runs the owner check, and decides what to do.

The STM32's decision rule:

| Model score | Status |
|---|---|
| 0 to 39 | normal |
| 40 to 69 | step-up |
| 70 to 100 | duress |
| missing, out of range, or a sensor veto | duress |

The model can raise the alarm but never lower it, and anything odd fails closed.

## The decoy

Under duress nothing looks different. The requester gets "accepted", the envelope has the same shape and size, and it's signed by the same keys. The status is mixed into the STM32's HMAC tag, and only the verifier holds the tag key, so only the verifier can tell which status it was. Linux never learns it either, so malware on the board can't tip the attacker off. What happens next (holding the transfer, a silent alert) is up to the customer's system.

## The owner check

The STM32 also attests a small sensor summary: grip, tremor, humidity, temperature, moisture, click hold time, how still the mouse was, movement speed and click impulse. The tag covers a hash of it, so Linux can't change it. The verifier compares those numbers with the registered user's own baseline for that time of day and gives an owner score from 0 to 100:

| Owner score | Result |
|---|---|
| 60 and above | looks like the owner, carry on |
| 35 to 59 | uncertain, returned to the customer as step-up |
| below 35 | not the owner, rejected quietly |

A rejected hand gets "unavailable", the same answer as every other failure, with no score or hint. After three rejections in ten minutes the verifier locks that user and records an alert. Until there are 20 samples, the check is advisory and rejects nobody, so the real owner doesn't get locked out on day one. Only approvals that passed as normal are added to the baseline, so someone else using the mouse can't teach it their hand.

## Edge cases

- **Over-the-shoulder rule.** Coworkers and people walking past don't count. The camera only flags someone who is close and facing the screen for 3 seconds or more. Camera frames stay in memory and are never stored.
- **Hand on the mouse.** Readings only count while a palm is on the grip, so a mouse left on the desk teaches nothing.
- **Back from a run.** After 5+ minutes away from the mouse, sweat or shake that is high but falling is treated as recovery. The body score is capped below the duress threshold, so that alone can't signal duress.

## What we gave up

No screen means no trusted display, so malware on the laptop could show one transfer and send another, and the user's normal click would approve it. The verifier binds the exact request, but the user can't check it on the device.

The STM32 sees a real click but not which click. Malware could wait for any ordinary click and try to arm its own request in the 1.5 second window. The short window and the rate limit make that harder, and it can't happen while nobody is using the mouse.

There's no deliberate "I'm being forced" signal. Duress is detected passively, so a very calm victim could be missed and a bad day could raise a false alarm. The owner check is statistical and we haven't measured its error rates.

The YubiKey without a touch proves the key is plugged in, not that someone chose to approve. That's why it's always paired with the STM32's click tag.
