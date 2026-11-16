# YuDuino: peace of mind in a new world

*Project overview by Jonah and Alex. Built at DurHack 2026 on an Arduino UNO Q with a YubiKey 5 NFC. **2nd place in the RS / Arduino track.** Updated 16 November 2026 to match the [pitch deck](../presentation/YuDuino-DurHack-2026-pitch.pdf).*

Wiring: **[hardware plan](HARDWARE-PLAN.md)**. Track and result: **[challenges](CHALLENGES.md)**. Cryptography: **[YuSeal crypto design](CRYPTO.md)**. The model: **[Edge Impulse](EDGE-IMPULSE.md)**.

## 1. The pitch

2026 is one of the worst years for security on record: Black October (the Binance attack and the PHP attack), state-sponsored attacks, huge amounts of capital invested in breaches, and open-weight AI models making attacks more accessible than ever. Transaction desks need a unique solution, and they need it fast.

**YuSeal** gives every security measure you could want going into 2027:

- an **ML-DSA post-quantum seal** (NIST FIPS 204);
- **keys never leave the hardware**;
- **STM32 click attestation** (a real finger made the click);
- **AES-256-GCM** encryption at rest;
- a **private, chip-derived unlock salt**;
- a **tamper-evident audit chain**.

**But something is missing:** the best encryption doesn't stop someone standing at your desk forcing you to approve. So **the key hides in plain sight, inside an office mouse**:

- **Invisible.** It looks and works completely like an office mouse.
- **Zero input.** No PIN, no screen, no additional buttons.
- **It knows your hand.** It checks that it's you, and that you're okay, at the moment of a transaction.

## 2. Why it matters: the Binance heist (29 October 2026)

About **US$6.34 billion** was stolen from Binance hot wallets in under four hours, the largest crypto theft on record (about $2.85B was later frozen). The FBI and Chainalysis attribute it to North Korea's TraderTraitor (Lazarus) group.

1. **June:** a wallet engineer installed a tampered Homebrew from a search ad.
2. **September:** a second engineer ran a malicious "assignment" from a fake job interview.
3. **20 October:** the attacker used an internal AI tool to take over more engineers' machines and found a container deployment token.
4. **29 October:** they drove the wallet signing service directly, outside the normal approval process, including EIP-7702 delegations that kept draining a wallet after withdrawals were suspended.

No human approved those transactions, because the system never asked one. Every step relied on a **copyable credential** or a **compromised computer**. YuDuino's answer: the wallet won't sign without a sealed signature that only exists after the owner's real hand physically clicks on the mouse.

Sources: [Binance initial report](https://x.com/binance/status/2117626126214504729), [Reuters, 3 Nov 2026](https://www.reuters.com/world/binance-says-hackers-used-fake-job-interview-compromise-computer-before-63-2026-11-03/), [Chainalysis](https://www.chainalysis.com/blog/binance-exploit-latest-findings-and-response/).

## 3. Hardware

| Part | Role |
|---|---|
| **Arduino UNO Q** | The brain. **STM32 side** (the trusted core): reads the click and the sensors, keeps the per-hour baseline, makes the final decision and the tag. **Linux side:** YubiKey, the ML-DSA key, camera, the anomaly model |
| **Arduino USB-C hub, power adaptor, USB-C cable** | Power, camera and YubiKey on the UNO Q's single USB-C port |
| **Arduino USB camera** | The over-the-shoulder rule: is someone close and watching the screen? Frames stay in memory on the board |
| **YubiKey 5 NFC** | Proves who is approving, with no touch needed |
| **Modulino Movement** | Hand tremor and movement |
| **Modulino Thermo** | Palm temperature and humidity (sweat) |
| **DFRobot touch sensor** | Is a hand actually on the mouse? Readings only count while it is |
| **DFRobot moisture sensor** | A second sweat and contact signal |
| **The mouse's own click** | The trigger: the STM32 sees the real physical click on "process transaction" |

## 4. How it works

**Knowing it's you (sensing).** Every minute you use the mouse, it records how you grip, move, sweat and click, and builds a personal profile on the device. A stranger's hand doesn't match your patterns, so they are quietly rejected with an ordinary-looking failure.

**Spotting duress (analysing).** When you click to make a transaction, your last minute is compared against your baseline. Stress shows up in several places at once: a tighter grip, more tremor, more sweat, a warmer palm, a sharper click. No single sensor decides: a locally hosted anomaly detection model uses all the data channels to reach a conclusion. Duress is judged **only at the moment of a transaction**; everyday use is learned from, never judged.

**The approval.**

1. **Request:** a transfer request arrives with a one-time nonce and an expiry.
2. **Click:** the user clicks "process transaction" like any other button. The STM32 sees the real click.
3. **Arm and unlock:** the STM32 only arms for a fresh click and releases the chip-derived salt that lets the YubiKey (no touch) unlock the post-quantum key.
4. **Analyse:** the last minute against the baseline, scored by the anomaly model.
5. **Seal:** the STM32 makes a tag over the status (normal or duress), the request digest and the click. Under duress the envelope looks identical, but the hidden status says duress, so it is a **decoy**.
6. **Check:** the customer's verifier checks all three proofs (YubiKey, STM32 tag, ML-DSA seal) and the owner check, and decides what to do.

**Fails closed:** no model, a model fault or a malformed output counts as duress, and the click, the YubiKey and the STM32 tag are always required.

## 5. Key design decisions

1. **Keeping it local.** We originally used Gemini and Tiger Data. We moved to storing user data on the device and using classical ML rather than a cloud LLM. Profile data and the model are AES-256-GCM encrypted on the board. Nothing leaves the device.
2. **Edge cases.** Coworkers and passers-by don't count (the over-the-shoulder rule), and readings only register while your hand is on the mouse.
3. **K-means anomaly detection.** Trained on 2000 calm rows; 17 input columns go into a K-means anomaly block. The inputs measure how far you are from your own mean, so it is personalised without retraining: z = (x − μ) / σ against your mean for that time of day.
4. **Someone just back from a run.** After 5+ minutes away from the mouse, if sweat or shake is high but falling, that's recovery from exercise. The body score is capped below the duress threshold, so that alone can't signal duress.

## 6. Release a key, never an "OK"

There is **no "approve = true" message anywhere**, because anyone who controls the computer sending it could spoof it. The **verifier** (whatever actually holds the wallet key: an HSM, co-signing server or smart contract) rebuilds the hash from the transaction it is about to run and checks the signatures, nonce and expiry itself. Only then does it sign.

- Setting "approved" on a hacked laptop does nothing: the verifier never reads flags.
- Swapping the destination after signing changes the hash, so the signature fails.
- Replaying an old approval fails: its nonce is used or expired.
- The check must be the **last step before signing, with no other route in**. That back route is exactly what the Binance attackers used.

## 7. Traceability: who approved it

- **One YubiKey per person**, never shared. The verifier maps each public key to a named approver.
- **Genuine hardware:** the YubiKey's attestation certificate proves the key was made inside a real YubiKey.
- **Tamper-evident log:** each approval entry includes the hash of the previous one, so nobody, including an insider, can quietly edit history. A copy can be kept on the microSD.

## 8. Honest limits

- **No screen**, so malware on the laptop could show one transaction and request another; the verifier binds the exact request, but the user can't see it on the device.
- **Stress isn't always duress.** The over-the-shoulder rule and the recovery rule handle the common cases; the owner check is statistical and can turn away the real owner.
- **The UNO Q has no dedicated secure element.** Keys and the final decision stay on the STM32 side.
- **Unverified on the board:** see the status table in the [README](../README.md#status).

## 9. Demo

We opened with the Binance attack, held up a "YubiKey with a quantum seal", then revealed the mouse that had been plugged in the whole time: passive, on-device analysis with zero input. Then a live staged-duress demo: one teammate "threatens" the other at the desk, and the approval goes through as a decoy.
