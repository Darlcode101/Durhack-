# YuSeal design brief

*Written 14 November 2026, 20:05. This is the brief the YuSeal v2 redesign was written against. If you (or an AI assistant) change the design later, re-read this first and check the change against every section.* Back to the **[crypto design](CRYPTO.md)** · **[build flow](BUILD-FLOW.md)**.

## 1. The job

Design the cryptography and authentication for YuDuino so that an approval:

1. **can only be made by a named person who is physically present**, pressing real buttons and touching a real YubiKey;
2. **covers exactly what that person saw** on a display the laptop does not control;
3. **carries a hidden duress signal** that the attacker in the room cannot detect, at the time or afterwards;
4. **can't be forged, replayed, altered or redirected**, today or by a future quantum computer;
5. **leaves a permanent record** of who authorised what;
6. **can be built by four students on the hardware we have before 11:00 on Sunday**, wave by wave, with a working demo at the end of every wave.

Point 6 is as binding as the others. A design that can't be built this weekend is a failed design.

## 2. Fixed facts (do not design around these, design with them)

**Hardware**

- Arduino UNO Q: a Linux computer (Qualcomm QRB2210, Debian, Wi-Fi, USB) and a separate STM32U585 microcontroller on one board. They talk over the Bridge (remote procedure calls).
- The STM32 runs the sketch. It owns the **8×13 LED matrix**, the Qwiic port (Modulino Buttons, Movement, Thermo) and the header pins (touch on D2, moisture on A1). Linux can't press a button or light the matrix except by asking the STM32.
- Linux owns the camera, microphone, network, and the USB port the YubiKey plugs into.
- YubiKey 5 NFC: FIDO2 with P-256 signatures and hmac-secret. No post-quantum algorithms. Touch is sensed inside its chip.
- No secure element, no screen, no fingerprint reader, no NFC reader. Three buttons (A, B, C).
- Not yet verified on our board: persistent storage from a sketch, a random number generator from a sketch, the LED matrix text call, Bridge argument types. **The design must not depend on any of them**, and must say where it would use them once verified.

**Decisions already made by Jonah**

- A signature or key is released, never an "OK" message.
- Cannot be operated remotely: a physical button press is required and the device screen shows exactly what is being approved.
- Under duress, a decoy that looks identical to the attacker, which the verifier treats as a silent alarm.
- Gemini alone does the duress calculation. No reply, a late reply or a malformed reply means the decoy. Pinned HTTPS.
- The final decision stays on the STM32.
- Works without biometrics; sensors only detect duress.
- Quantum-proof, with interest in symmetric and hash-based options.
- Every action traceable to who authorised it.
- The Vultr guardian can lock and alert but never approve.
- Simple, multipurpose parts. Keep the prototype simple.

**The team's existing code** (`app/python`, `app/sketch`): YubiKey over python-fido2, an encrypted ML-DSA key store, a Gemini call with a structured schema, a sketch that sends sensor features **and the typed PIN** to Linux.

## 3. Who we are defending against

Rank every design choice against these, strongest first.

| Attacker | What they have | What they want |
|---|---|---|
| **Remote, root on the Linux side** (the Binance pattern: poisoned package, stolen token) | Everything Linux can see and call: files, memory, the Bridge, the YubiKey's USB traffic, the network | An approval the user never saw, or a changed one |
| **In the room, coercing the user** | Sight of the device, the screen, the button presses; may know how YuDuino works; may know the user's normal PIN from watching | A real approval; to know whether an alarm was raised |
| **Later, with the seized device** | The board, the SD card, time, maybe lab equipment | Proof the victim raised the alarm; keys for future forgery |
| **On the network** | Can block, delay, replay and read traffic; can record it for a future quantum computer | Force a "calm" verdict; replay approvals; read biometric features |
| **Insider or hacked guardian** | The server, its keys and database | Approve something; rewrite history; learn who raised alarms |
| **Thief** | YubiKey, or device, or a copy of the key file, but not all with the PIN | Any approval |
| **Future quantum computer** | Breaks P-256, RSA, X25519 | Forge signatures; decrypt recorded traffic |
| **Supply chain** | A malicious library or firmware build | Any of the above |

For each attacker the design must state: what stops them, what they can still do, and what evidence is left.

## 4. Questions the design must answer

**Presence and display**
- If Linux is fully compromised, what exactly prevents an approval with no button press? It must be something Linux cannot compute.
- What binds the approval to the text on the LED matrix? Who computes that hash?
- The matrix is tiny. If only the last characters of a destination are shown, an attacker can make an address with the same ending. How does the display identify the destination unambiguously?
- Every field in a request must be either shown or refused. Nothing unshown may change what happens.

**Duress**
- Who learns that duress was signalled? List every component and say whether it knows. The fewer the better; ideally only the STM32 and the guardian.
- Can anyone tell a duress approval from a normal one by key, size, timing, structure, screen, sound, network traffic, or what happens in the next minute?
- The attacker may watch the PIN being typed. How does the duress PIN avoid looking different?
- What if the attacker cuts the network, unplugs a sensor, or puts a sign in front of the camera?
- If the device is seized afterwards, what can be learnt about past alarms?
- A false alarm must be cheap. A missed alarm must still hit other defences.

**Keys**
- Where is every secret, at rest and in use? Who else could read it?
- Which keys can be replaced, and how? Which are single points of failure?
- What does each key prove, and to whom? Symmetric keys prove nothing to third parties; say where that matters.
- No secret may depend on a short PIN that can be guessed offline.

**Protocol**
- Replay, reorder, redirect to another service, mix parts of two approvals, downgrade the algorithm: each needs a named defence.
- The device has no trusted clock. Who enforces expiry?
- State must survive lost messages and power cuts without getting stuck or reusing anything.

**Failure modes** (each needs a defined, safe outcome)
- Wi-Fi down; Gemini slow, down or returning nonsense; guardian down.
- YubiKey unplugged mid-approval; wrong YubiKey.
- Wrong PIN; five wrong PINs; grip released.
- Power cut between any two steps.
- The Bridge call fails or is called out of order.

**People**
- Enrolment, a lost YubiKey, a lost or broken device, someone leaving the team, a forgotten PIN.
- Accessibility: anything read aloud must not reveal the status.
- Privacy and law: sensor readings are biometric-like data; emotion recognition at work is restricted under the EU AI Act. What leaves the device, what is stored, for how long?

**Build**
- For every part: which chip, which file, which language, which wave, who on the team, and how to test it without the hardware.
- What is the smallest thing that can be demoed after each wave?
- What happens to the design if an unverified hardware feature turns out not to exist?

## 5. Quality bar

- **Plain words.** A first-year student must be able to follow every section. Define a term the first time it appears.
- **Standard parts only.** NIST-standardised algorithms, used the way they were designed to be used. No invented ciphers. Invented protocols must be simple enough to check by hand and must be tested.
- **Small trusted core.** The code that must be right should fit on one screen and run on the microcontroller.
- **Every claim is tested or marked as untested.** Code that hasn't run on the board says so.
- **Honest.** "Unbreakable" is not available. Name the weak spots in order of seriousness, and never hide one to make the design look better.
- **Fail closed.** When anything is missing, late, malformed or out of order, the result is hold and alert, never approve.
- **One format.** Payments, logins and admin changes use the same envelope and the same verifier.
- **Agile.** Every envelope names its suite, so algorithms can be replaced.

## 6. Review of v1 against this brief

YuSeal v1 (the first version of [CRYPTO.md](CRYPTO.md)) got the envelope, the hybrid signatures, the sealed status and the audit log right. Held against this brief it fails in seven places:

| # | Gap in v1 | Why it matters |
|---|---|---|
| 1 | **Nothing in the envelope came from the STM32.** Presence rested on the YubiKey touch alone, and Linux chose what the YubiKey signed | Root on Linux could wait for a genuine touch and swap in another request. The LED matrix wasn't cryptographically bound to anything |
| 2 | **Linux knew the duress result.** It saw the typed PIN, opened the wraps and built the sealed box | Malware on the board could tell the attacker an alarm was raised |
| 3 | **Destination shown as its last 6 characters** | Addresses with a chosen ending are cheap to generate |
| 4 | **Expiry used the device's clock** | The device has no trusted clock |
| 5 | **Two PIN wraps on disk**, and the one that usually opens is the normal one | Leaks which PIN is which over time; the PIN check ran on Linux, so the lockout could be bypassed |
| 6 | **The plan to move ML-DSA and AES to the STM32 was Wave 4 "if time"** | The most important security step was the least likely to happen |
| 7 | **The duress PIN could look different from the normal one** to someone watching | An informed attacker in the room would notice |

The v2 redesign fixes all seven with one idea: give the STM32 a small job only it can do, using nothing but SHA-256.
