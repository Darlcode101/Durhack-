# YuPico: hardware approval you can't fake, even under threat

*Project overview by Jonah, compiled 14 November 2026. Built on the Arduino UNO Q with a YubiKey 5 NFC.*

## 1. The pitch: selling peace of mind

YuPico is a desk-sized approval device. Moving money, logging in to production servers, or letting an AI agent act all require a named person to physically approve on it. Every approval is a cryptographic signature, never an "OK" message, so malware can't fake one. It is also the only approval device that tries to protect the approver from **someone standing next to them forcing them to approve**.

- Hardware keys (YubiKeys, Ledger devices, HSMs) are the best form of security available today.
- **None of them can handle an in-person attacker forcing someone to enter their PIN.**
- YuPico watches for signs of duress (a scared voice, trembling hands, a changed touch, sweat). If the user seems to be under duress, it hands the attacker a **fake approval** that looks real but moves nothing and raises a silent alarm.

## 2. Why it matters: the Binance heist (29 October 2026)

About **US$6.34 billion** was stolen from Binance hot wallets in under four hours, the largest crypto theft on record. About $2.85B was frozen. The FBI and Chainalysis attribute it to North Korea's TraderTraitor (Lazarus) group.

How it happened, from Binance's own report:
1. **June:** a wallet engineer installed a tampered Homebrew from a search ad.
2. **September:** a second engineer ran a malicious "assignment" from a fake job interview.
3. **20 October:** the attacker used an **internal AI tool** to take over more engineers' machines and found a **container deployment token** on a laptop.
4. **29 October:** they deployed a container and drove the **wallet signing service** directly, outside the normal withdrawal process. About 50 signing requests set up EIP-7702 delegations that kept draining a wallet after withdrawals were suspended. Because the wallet used MPC, there was no single key to revoke the delegations quickly.

Every step after the first infection relied on a **copyable credential** or an **approval made on a compromised computer**. That is the gap YuPico closes.

Sources: [Binance initial report](https://x.com/binance/status/2117626126214504729), [Reuters, 3 Nov 2026](https://www.reuters.com/world/binance-says-hackers-used-fake-job-interview-compromise-computer-before-63-2026-11-03/), [Chainalysis](https://www.chainalysis.com/blog/binance-exploit-latest-findings-and-response/).

## 3. Core idea: release a key, never an "OK"

The single most important design rule: **there is no "approve = true" message anywhere.** A message like that can be spoofed by anyone who controls the computer that sends it.

Instead:
1. A request arrives (from a laptop, server or AI agent) with a fresh one-time **nonce** and a **2-minute expiry**.
2. YuPico decodes the raw request and **shows exactly what it is** on its own screen: action, amount, asset, destination, and any unusual permission (like an EIP-7702 delegation). Anything too long to display in full is refused, not cut off.
3. The user confirms and **physically touches the YubiKey**. The YubiKey **signs a hash of exactly what is on screen** with a private key that never leaves its chip.
4. The UNO Q adds a **post-quantum signature** (section 4).
5. The **verifier**, which is whatever actually holds the wallet key, rebuilds the hash from the transaction it's about to run and checks both signatures, the nonce and the expiry. Only then does it sign the real transaction.

Why this can't be faked:
- **Setting "approved" on a hacked laptop does nothing.** The verifier never reads flags.
- **Editing a signature breaks it.** Forging one without the private key would take about 2^128 operations.
- **Swapping the destination after signing changes the hash**, so the signature no longer matches.
- **Replaying an old approval fails** because its nonce is used or expired.
- **The YubiKey's touch is sensed inside its own secure chip** and signed into the approval. Software, local or remote, can't press it.

**Where the check runs matters most.** If an application checks the signature and then passes an "OK" on, that OK becomes the new weak point. So the signature must be checked by the HSM or smart contract that holds the wallet key, as the last step before signing, with no other route in. This is exactly the path the Binance attackers went around.

## 4. Post-quantum security

A large quantum computer running **Shor's algorithm** would break today's elliptic-curve and RSA signatures, including everything a YubiKey 5 signs with. YuPico is built to survive that:

- **Hybrid signatures.** Every approval carries **two** signatures: the YubiKey's P-256 signature and an **ML-DSA** signature (NIST FIPS 204, 2024). The verifier requires both. A forger must break the elliptic-curve maths *and* the lattice maths, and steal from both devices.
- **Why the UNO Q signs ML-DSA:** the YubiKey 5 has no post-quantum signing. The UNO Q's STM32U585 microcontroller (Arm Cortex-M33 with TrustZone) holds the post-quantum key and signs.
- **Hash-based firmware signing.** Firmware updates are signed with LMS or SLH-DSA, which rely only on hash functions and stay safe after quantum computers arrive.
- **Crypto-agility.** Every message carries an algorithm ID, so algorithms can be swapped without redesigning the hardware.
- **What stays safe anyway:** hash functions and symmetric ciphers (SHA-256/384, AES-256) only lose about half their strength to quantum search (Grover's algorithm).
- **Why not symmetric-only (stream ciphers, MACs)?** They are quantum-safe, but the verifier would hold the same key and could forge approvals. That breaks traceability. Symmetric crypto is an extra layer, not the proof.

## 5. Duress detection

The problem no product solves: an attacker in the room, forcing the approver to enter their PIN and tap.

**Signals YuPico reads while the user approves:**

| Signal | Sensor | What it looks for |
|---|---|---|
| **Voice** | Microphone | Fear and stress in the voice (V7 Labs analysis) |
| **Tremor** | Motion sensor (accelerometer) | Shaking hands while holding or pressing the device |
| **Touch pattern** | Touchscreen | Changed pressure, speed and rhythm compared with the user's normal touch |
| **Sweat** | Skin conductance (GSR) sensor | Sweaty palms, a classic stress response |
| **Face** | Camera | Fearful expression, or another person in frame |
| **Pulse** | Heart-rate sensor | A racing heart |

**Decision:** all signals are combined and analysed by **Google Gemini** to decide whether the user is under duress.

**Response:** if the user seems to be under duress, YuPico grants a **fake OK**. To the attacker it looks exactly like a real approval: same screen, same sounds, same timing. *(Details of the fake OK to follow.)* One way to build it: the signed approval carries a hidden duress marker that only the verifier recognises. The verifier then freezes the action and raises a silent alarm instead of moving funds.

**Learning:** an online database provided by a hackathon sponsor stores what a user under duress responds like. Every false alarm the user corrects is fed back, so the system improves the more it is used.

**Design rule: AI can only make things safer.** A "danger" verdict switches to the fake OK. An "all clear" verdict never approves anything on its own; the YubiKey signature is still required. Otherwise, faking the AI's answer would become a way to get approvals through.

## 6. Onboard processing and side channels

**Goal:** all processing happens on the device, so nothing sensitive is exposed to network side channels or logged in someone else's cache.

Why this matters:
- **Encrypted traffic still leaks.** Packet sizes and timing from AI services have revealed the content and topics of prompts: [Weiss et al., USENIX Security 2024](https://cdn.arstechnica.net/wp-content/uploads/2024/03/LLM-Side-Channel.pdf), [Microsoft's Whisper Leak, Nov 2025](https://www.microsoft.com/en-us/security/blog/2025/11/07/whisper-leak-a-novel-side-channel-cyberattack-on-remote-language-models/).
- **Cloud processing creates logs and caches** of biometric data that could be subpoenaed, leaked or replayed.
- **AI makes physical side-channel attacks cheaper.** Deep learning recovers keys from power and EM traces with far fewer measurements ([SoK, ACM Computing Surveys](https://dl.acm.org/doi/full/10.1145/3569577)). So the ML-DSA code on the STM32U585 must be a masked (side-channel-protected) implementation.

How the UNO Q helps: its Qualcomm QRB2210 runs Debian Linux on four Cortex-A53 cores with 2–4 GB of RAM, enough to run sensor and voice models locally. The STM32U585 handles the real-time sensors and the cryptography, separate from the Linux side.

> **Open tension to resolve:** Google Gemini and V7 Labs are cloud APIs, and the sponsor's learning database is online. That conflicts with "all processing is done onboard". Options:
> 1. **Run everything locally:** Google's open **Gemma** models (small versions can run on the UNO Q's Linux side) plus on-device sensor models. This fully meets the onboard goal.
> 2. **Send only a summary:** process raw voice, video and sensor data on the device and send Gemini only anonymous scores ("tremor 0.8, voice stress 0.6"). Pad every message to a fixed size and send at fixed intervals, so traffic analysis reveals nothing.
> 3. **Cloud only as a fallback**, with the device deciding on its own if the network is down. Since AI can only make things safer, a failed or delayed cloud call can only lead to a fake OK, never a real approval.

## 7. Hard requirements

1. **Cannot be operated remotely.** Someone has to physically press: the YubiKey's touch sensor, sensed inside its secure chip. An optional physical button can also switch on the NFC reader's power through a hardware circuit, so no software can reach the YubiKey unless the button is held.
2. **The screen shows exactly what gets signed.** The hash the YubiKey signs is computed from the displayed bytes, never from a summary supplied by the laptop or an agent.
3. **No remote control paths.** No SSH server, remote desktop or over-the-air update on the device. Firmware changes only over USB with a physical button held, and only signed firmware runs.
4. **No "OK" signal anywhere.** Only signatures, checked by whatever holds the wallet key.
5. **Doesn't rely only on biometrics.** The YubiKey, its PIN and a physical touch are the proof. Biometrics are used for duress detection and as an optional extra layer.

## 8. Traceability: who approved it

- **One key per person, never shared.** The verifier maps each public key to a named approver.
- **Genuine hardware:** the YubiKey's attestation certificate, signed by Yubico, proves the key was made inside a real YubiKey.
- **Tamper-evident log:** each approval is appended to a log where every entry includes the hash of the one before. The latest hash can be published publicly (for example on-chain), so even the operator can't rewrite history.
- **Big actions need 2 of 3 approvers**, each logged by name.

## 9. Remote use: SSH and AI agents

People and agents can **request** actions from anywhere. Only a person holding their YuPico can **approve** them.

- **SSH:** staff log in with an `ed25519-sk` key on their YubiKey (PIN and touch). The login can only submit requests (OpenSSH `ForceCommand`), never open a shell. Holding a YuPico alone never grants access.
- **AI agents:** agents call YuPico before risky actions (pay, delete, deploy). The screen shows a summary built from the request's structured fields, not text the agent wrote, so a hijacked agent can't word its way past the approver.

## 10. What makes it different

Ledger Enterprise already offers hardware approval devices with trusted screens, and Fireblocks offers phone-based approvals. YuPico adds what they don't:

- **Duress detection with a fake OK**, the headline feature. None of them handle in-person coercion.
- **Hardware approval for changes to the wallet system itself** (deployments, permissions), the route used in the Binance heist.
- **A hardware emergency brake:** pre-approved freeze-and-revoke actions that 2 of 3 people can trigger instantly, which Binance lacked.
- **Approval for AI agents**, not just people.
- **Hybrid post-quantum signatures.**
- **No automatic approvers** at all, by design.
- **Cheap and open**, built on an off-the-shelf Arduino UNO Q.

## 11. Hardware (Arduino UNO Q build)

| Part | Job |
|---|---|
| **Arduino UNO Q** | Linux side (QRB2210) runs the screen, camera, microphone and duress models; microcontroller side (STM32U585) reads sensors and signs ML-DSA |
| **YubiKey 5 NFC** | Holds each approver's private key; touch = physical approval |
| **PN532 NFC reader** | Talks to the YubiKey when it's tapped |
| **Touchscreen** (via the UNO Q's USB-C video output) | Shows exactly what's being approved; PIN entry; touch-pattern analysis |
| **USB webcam with built-in mic** | Face and voice for duress detection |
| **Motion sensor** (Modulino Movement, Qwiic) | Hand tremor |
| **GSR sensor** | Sweat |
| **Heart-rate sensor** (MAX30102) | Pulse |
| **R503 fingerprint sensor** | Optional identity layer; also where the finger rests for the GSR and pulse sensors |
| **USB-C hub** | Connects the screen, camera and power to the UNO Q's single USB-C port |

The UNO Q's header pins run at 3.3 V.

## 12. Limitations and honest risks

| Limitation | Mitigation |
|---|---|
| Doesn't stop the initial malware infection | Endpoint security; YuPico limits what stolen access is worth |
| Duress detection can give false alarms or miss real duress | AI can only make things safer; the sponsor database learns from false alarms; time delays and 2-of-3 approval as backstops |
| Cloud AI (Gemini, V7 Labs) conflicts with "onboard only" | See section 6 options; local Gemma or summary-only scores |
| The UNO Q has no dedicated secure element for the post-quantum key | Masked ML-DSA, TrustZone, tamper-evident case; move it to a secure element when available |
| A compromised device could show one transaction and sign another | Signed firmware only, no remote updates, tamper detection; the YubiKey still needs a physical touch |
| The verifier's own code and key list become the target | Keep it tiny and audited, run it in an HSM or smart contract, require multi-person approval to change keys |
| Lab-grade physical attacks on the hardware | YubiKey firmware 5.7+ (after the EUCLEAK fix), tamper wipe, fast revocation |
| Blockchains themselves still use elliptic-curve keys | Outside YuPico's control; it protects the approval step |

## 13. Hackathon goals

- Enter **every side-track challenge**, including the **hackiest hack** (proudly held together with cardboard, hot glue and crocodile clips).
- **Demo:** replay the Binance attack. A laptop "attack script" sends a transfer request, YuPico shows it, and nothing moves without a real tap. Then show a forced approval: the duress check triggers, the attacker sees "Approved", and the verifier silently freezes the funds.

## 14. Open decisions

- [ ] Fake OK design (details to come)
- [ ] Gemini: cloud, summary-only, or local Gemma (section 6)
- [ ] PIN on the device plus touch, daily unlock, or touch only
- [ ] Verifier: HSM, co-signer server, or smart contract
- [ ] Which sponsor database, and what data it may store
