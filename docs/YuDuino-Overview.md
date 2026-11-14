# YuDuino: hardware approval you can't fake, even under threat

*Project overview by Jonah, 14 November 2026. Built for DurHack on an Arduino UNO Q with a YubiKey 5 NFC. (Formerly "YuPico"; renamed because the build no longer uses a Raspberry Pi Pico.)*

To wire it up, see the step-by-step **[hardware plan](HARDWARE-PLAN.md)**. For the team schedule and software checklist, see **[PLAN.md](PLAN.md)**. For how YuDuino targets each DurHack challenge (RS/Arduino, Tagged, Gemini, Tiger Data and add-ons), see the **[challenge plan](CHALLENGES.md)**.

## 1. The pitch: selling peace of mind

YuDuino is a small desk device that sits between a person and anything dangerous they can approve: moving money, deploying to production, letting an AI agent act. Nothing happens until a named person physically approves on it. Each approval is a **cryptographic signature, never an "OK" message**, so malware on a laptop can't fake one.

Hardware keys (YubiKeys, Ledger devices, HSMs) are the best security available today, but **none of them help when someone in the room forces you to enter your PIN**. YuDuino watches for signs of duress while you approve: shaking hands, sweaty palms, an odd PIN rhythm, a scared voice, a second face in the camera. If something is wrong, it hands the attacker a **fake approval** that looks real but moves nothing and silently raises the alarm.

## 2. Why it matters: the Binance heist (29 October 2026)

About **US$6.34 billion** was stolen from Binance hot wallets in under four hours, the largest crypto theft on record (about $2.85B was later frozen). The FBI and Chainalysis attribute it to North Korea's TraderTraitor (Lazarus) group.

1. **June:** a wallet engineer installed a tampered Homebrew from a search ad.
2. **September:** a second engineer ran a malicious "assignment" from a fake job interview.
3. **20 October:** the attacker used an internal AI tool to take over more engineers' machines and found a container deployment token.
4. **29 October:** they drove the wallet signing service directly, outside the normal approval process, including EIP-7702 delegations that kept draining a wallet after withdrawals were suspended.

No human approved those transactions, because the system never asked one. Every step relied on a **copyable credential** or a **compromised computer**. YuDuino's answer: the wallet won't sign without a signature that only exists after a person presses a physical button, having seen the real transaction on a display the laptop doesn't control.

Sources: [Binance initial report](https://x.com/binance/status/2117626126214504729), [Reuters, 3 Nov 2026](https://www.reuters.com/world/binance-says-hackers-used-fake-job-interview-compromise-computer-before-63-2026-11-03/), [Chainalysis](https://www.chainalysis.com/blog/binance-exploit-latest-findings-and-response/).

## 3. The kit and what each part does

Everything below is in our hackathon inventory except the YubiKey, which we bring.

| Part | Role in YuDuino | Connects to |
|---|---|---|
| **Arduino UNO Q** | The brain. Its Linux side (Qualcomm QRB2210) runs the camera, microphone, duress scoring and Gemini call. Its microcontroller side (STM32U585) reads sensors in real time and will hold the post-quantum key | Everything |
| **UNO Q built-in LED matrix** (8×13) | The **trusted display**: scrolls the amount and destination being approved, then the result | Built in |
| **Arduino USB-C hub** | The UNO Q has one USB-C port; the hub splits it for power, camera and YubiKey | UNO Q USB-C |
| **Arduino power adaptor** + **USB-C to C cable** | 5 V 3 A into the hub's power-in port | Hub |
| **Arduino USB camera, Full HD, with mic** (USB-A) | Face count (is someone else there?), expression, voice stress; pulse from the face as a stretch goal | Hub USB-A |
| **YubiKey 5 NFC** | Proves **who** is approving. Its private key never leaves its chip, and the touch is sensed inside the chip, so software can't press it | Laptop (milestone 1), then hub USB-A |
| **Modulino Buttons** | PIN entry as a sequence of A, B and C presses; approve and reject; press rhythm for duress; a secret **duress PIN** | Qwiic chain |
| **Modulino Movement** | Hand tremor from the accelerometer, inside the grip | Qwiic chain |
| **Modulino Thermo** | Palm temperature and humidity. Humidity near the palm is our best sweat signal | Qwiic chain |
| **DFRobot touch sensor v2** | "Is the grip actually being held?" Gates the capture window | Pin D2 |
| **DFRobot moisture sensor v2** | Second, crude sweat/contact signal. Only its change from the user's own baseline counts | Pin A0 |
| **Male-to-male jumpers** | Wiring the two DFRobot sensors into the UNO Q's female headers | Headers |
| **32 GB microSD + Icy Box** | Spare storage: offline backup of the audit log and the user's baseline | Not needed for the core |

The DFRobot sensors and Modulinos live in one **handheld grip** (cardboard and hot glue are fine), so every approval happens while the user is holding it.

## 4. How an approval works

1. **Request.** A laptop, server or AI agent asks for an action. The request carries a one-time nonce and a 2-minute expiry.
2. **Show.** The UNO Q decodes the raw request and scrolls it on the LED matrix: action, amount, the last characters of the destination, and any unusual permission. Anything too long to show is refused, never cut short. The laptop screen is never trusted for this.
3. **Hold and enter PIN.** The user holds the grip (touch sensor confirms it) and enters their PIN on the Modulino Buttons. An 8-second capture window records tremor, humidity, temperature, moisture, PIN rhythm, a camera frame and audio.
4. **Tap.** The user touches the YubiKey, which signs a hash of exactly what was shown.
5. **Score.** A rules engine compares the readings with the user's own resting baseline. Gemini looks at the frame and a summary of the readings. The final risk is whichever is higher.
6. **Respond.** Low risk: a real approval. Medium: ask for a second approver. Duress (or the duress PIN): a **fake approval**. The LED matrix shows exactly what a real one would, but the signature carries a hidden marker. The verifier freezes the action and sends a silent alert.

**Design rule: AI can only make things safer.** A "danger" verdict can switch to the fake approval; an "all clear" never approves on its own. The YubiKey signature is always required. PINs are never sent to Gemini.

## 5. Release a key, never an "OK"

There is **no "approve = true" message anywhere**, because anyone who controls the computer sending it could spoof it. The **verifier** (whatever actually holds the wallet key: an HSM, co-signing server or smart contract) rebuilds the hash from the transaction it is about to run and checks the signatures, nonce and expiry itself. Only then does it sign.

- Setting "approved" on a hacked laptop does nothing: the verifier never reads flags.
- Swapping the destination after signing changes the hash, so the signature fails.
- Replaying an old approval fails: its nonce is used or expired.
- The check must be the **last step before signing, with no other route in**. That back route is exactly what the Binance attackers used.

## 6. Post-quantum security

A large quantum computer running Shor's algorithm would break the elliptic-curve and RSA signatures a YubiKey 5 uses. YuDuino plans for that:

- **Two signatures per approval.** The YubiKey's P-256 signature plus an **ML-DSA** (NIST FIPS 204) signature from the UNO Q's STM32U585. The verifier requires both, so a forger must break both kinds of maths and steal from both devices.
- **The UNO Q key earns its place.** The YubiKey can't do post-quantum signing, and it can't see the duress result. The UNO Q key does both: it only signs after the duress check, and under duress it signs with the decoy marker.
- **Keep it on the microcontroller side**, never on the Linux side where camera and Gemini code run.
- **Crypto-agility:** every message names its algorithm, so algorithms can be swapped later.

For the hackathon, ML-DSA is a stretch goal; the YubiKey signature and the duress flow come first.

## 7. Onboard processing

Raw camera, audio and sensor data stays on the UNO Q. Encrypted traffic to AI services can still leak content through packet sizes and timing ([Weiss et al., USENIX Security 2024](https://cdn.arstechnica.net/wp-content/uploads/2024/03/LLM-Side-Channel.pdf); [Microsoft Whisper Leak, 2025](https://www.microsoft.com/en-us/security/blog/2025/11/07/whisper-leak-a-novel-side-channel-cyberattack-on-remote-language-models/)), and cloud logs of biometric data can leak or be subpoenaed.

For the hackathon, Gemini receives **one frame and a summary of scores**, never PINs or raw audio. If Gemini is slow or offline, the rules engine decides alone, and because AI can only raise risk, a failed call can never cause an approval. Later version: a small local model (such as Gemma) on the UNO Q's Linux side, and padded, fixed-interval messages.

## 8. Hard requirements

1. **Cannot be operated remotely.** A person must physically touch the YubiKey; the touch is sensed inside its chip.
2. **The display shows exactly what gets signed.** The signed hash is computed from the bytes shown, never from a laptop's summary.
3. **No remote control paths** on the device: no remote desktop or over-the-air updates. Firmware only over USB.
4. **No "OK" signal anywhere.** Only signatures, checked by whatever holds the wallet key.
5. **Doesn't rely only on biometrics.** The YubiKey, PIN and touch are the proof; sensors only detect duress.

## 9. Traceability: who approved it

- **One YubiKey per person**, never shared. The verifier maps each public key to a named approver.
- **Genuine hardware:** the YubiKey's attestation certificate proves the key was made inside a real YubiKey.
- **Tamper-evident log:** each approval entry includes the hash of the previous one, so nobody, including an insider, can quietly edit history. A copy can be kept on the microSD.
- **Big actions need 2 of 3 approvers.**

## 10. What makes it different

Ledger Enterprise offers approval devices with trusted screens, and Fireblocks offers phone approvals. YuDuino adds:

- **Duress detection with a fake approval**, the headline feature.
- **Hardware approval for changes to the wallet system itself** (deployments, permissions, delegations), the route used against Binance.
- **Approval gates for AI agents**, not just people.
- **Hybrid post-quantum signatures.**
- **Cheap and open**, built from off-the-shelf Arduino parts.

## 11. Limitations and honest risks

| Limitation | Mitigation |
|---|---|
| The LED matrix is tiny, so long transactions are hard to show | Show amount and destination tail only; refuse anything else; an HDMI screen on the hub in the next version |
| No real skin-conductance (GSR) or pulse sensor in the kit | Thermo humidity and moisture deltas from the user's own baseline; camera pulse as a stretch goal |
| Stress isn't duress (late, cold, coffee) | Soft responses only (second approver, silent alert), never a hard lockout; the duress PIN is the most reliable signal |
| A calm, well-informed attacker can beat physiological checks | Duress PIN, time delays and 2-of-3 approval as backstops |
| Doesn't stop the initial malware infection | It limits what stolen access is worth |
| The UNO Q has no dedicated secure element | Key on the microcontroller side only; signed firmware; secure element in a later version |
| Cloud Gemini conflicts with "everything onboard" | Scores-only summary for now; local model later |
| Emotion recognition is legally sensitive (the EU AI Act restricts it at work) | Frame it as context risk scoring; consenting teammates only on camera; frames never stored |

## 12. Hackathon goals

- **Demo:** replay the Binance attack. An "attack script" on the laptop requests a transfer; the LED matrix shows it; nothing moves without a real tap. Then a forced approval: the duress check fires, the attacker sees "OK", and the verifier silently freezes the funds.
- **Target challenges** (details in the [challenge plan](CHALLENGES.md)): RS/Arduino (main), Tagged "Information Hidden in Plain Sight" (optional), MLH Best Use of Gemini API, MLH Best Use of Tiger Data. Cheap add-ons: DEV, ElevenLabs, Vultr; Solana as a stretch.
- Use the free 3D printer for the grip, enclosure and YubiKey dock.

## 13. Open decisions

- [ ] Fake approval design details
- [ ] YubiKey on the laptop (WebAuthn) or directly on the UNO Q (USB)
- [ ] Gemini in the cloud with scores only, or a local model
- [x] Verifier: the guardian backend on a Vultr server (dashboard, verifier, silent alerts); a Solana devnet wallet program as a stretch goal
- [x] Sponsor database: Tiger Data, derived scores and labels only, written after the decision
- [x] Tagged framing: the body's duress signals are the hidden language, Gemini translates (secret gesture optional)
