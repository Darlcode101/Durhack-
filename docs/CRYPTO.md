# YuDuino cryptography: the YuSeal design

*Written 14 November 2026, evening of day one of DurHack.* Back to the **[overview](YuDuino-Overview.md)** · **[dev plan](DEV-PLAN.md)** · **[hardware plan](HARDWARE-PLAN.md)** · **[challenge plan](CHALLENGES.md)**

Working reference code: [`app/python/yuseal.py`](../app/python/yuseal.py), with 14 tests in [`app/python/test_yuseal.py`](../app/python/test_yuseal.py) (`cd app/python && python3 -m unittest test_yuseal -v`). It needs only `cryptography>=48`, which has ML-DSA and ML-KEM built in, so **no liboqs build on the board**.

## In one minute

Every approval YuDuino gives is a sealed envelope called **YuSeal**:

1. **What you saw.** The device builds the display text from the raw request itself and hashes exactly that. The laptop never describes the transaction to you.
2. **Proof you were there.** Your YubiKey signs that hash when you physically touch it. It names *who* approved.
3. **The hidden status.** A small encrypted box says *normal*, *needs a second approver* or *duress*. Only the guardian (the Vultr verifier) can open it. A duress box looks exactly like a normal one, byte for byte in size and shape.
4. **A post-quantum seal over everything.** The device signs all of the above with **ML-DSA-65**, so nothing can be swapped, replayed or forged, even by a future quantum computer.
5. **A permanent record.** Each envelope goes into a hash-chained, signed audit log, so nobody can quietly rewrite who approved what.

The attacker in the room sees the same screen, the same "accepted" reply and the same kind of envelope whether or not the alarm went off. That is the YuDuino language at the cryptographic level: the meaning is there, but only the guardian can read it.

## What "unbreakable" honestly means here

Nothing is unbreakable. What we can do is make sure that:

- **No single stolen thing is enough.** An attacker needs your YubiKey *and* your PIN *and* the device *and* your physical touch, and the verifier still checks the transaction itself.
- **The maths has two independent locks.** Approvals carry a classical signature (YubiKey, P-256) *and* a post-quantum one (ML-DSA-65). A forger must break both. Our long-lived roots use **SLH-DSA**, whose security rests only on hash functions, the most conservative assumption in cryptography.
- **When something does break, it fails safe and leaves evidence.** Missing, late or strange inputs mean *hold and alert*, never *approve*. Every decision is written to a log that can't be edited without it showing.

The weak spots that remain are listed in [Remaining weak spots](#remaining-weak-spots). In practice, attackers go for bugs, people and supply chains long before they attack the maths, so most of this design is about those.

## The building blocks

| Block | What it does for us | Why this one | Safe against quantum? |
|---|---|---|---|
| **ML-DSA-65** (FIPS 204, 2024) | The device's signature on every envelope and log entry | NIST's main post-quantum signature; fast; fits on the STM32 (about 80 KB of RAM to sign) | Yes |
| **SLH-DSA-SHA2-128s** (FIPS 205) | Signs the long-lived things: membership certificates, firmware, daily log checkpoints | Security rests only on SHA-256. If lattice maths (ML-DSA) is ever broken, this still stands. Slow and large, so used rarely | Yes |
| **YubiKey 5 FIDO2, ES256 (P-256)** | Proves a named person touched a genuine YubiKey for *this* request | Key can't leave the chip; touch sensed in the chip; attestation proves it's genuine | No, which is why it never stands alone |
| **YubiKey hmac-secret** | Turns "YubiKey + PIN" into a key that unlocks the device's signing key | One touch gives a 32-byte secret only that YubiKey can produce | Yes (it's symmetric) |
| **ML-KEM-768 + X25519** (FIPS 203, hybrid) | Agrees the guardian sealing key at enrolment; protects network traffic (hybrid TLS) | Safe if *either* holds | Yes |
| **AES-256-GCM** | The sealed status box; wrapping keys at rest | 256-bit keys stay strong even against Grover's algorithm; STM32 has it in hardware | Yes |
| **HKDF-SHA-256 ratchet** | A new sealing key after every approval; old ones erased | Forward secrecy: seizing the device later doesn't reveal past alarms | Yes |
| **SHA-256** | Every hash: request, display, log chain, Merkle tree | The STM32U585 has a SHA-2 accelerator; 128-bit security even against quantum search | Yes |

Every envelope names its suite (`YS1`), so we can swap algorithms later (for example to ML-DSA-87 or FN-DSA) without changing the format. That is **crypto-agility**.

## Who holds what: the key hierarchy

```
                 ┌───────────────────────────────────────────┐
                 │ ORG ROOT  (SLH-DSA, hash-based)           │  offline: created once on an
                 │ signs membership certs, firmware,         │  unplugged laptop, kept on the
                 │ revocations, daily log checkpoints        │  microSD; backup split 2-of-3
                 └───────────────┬───────────────────────────┘
          membership certificate │ "Jonah = this YubiKey + this device key, limits £X, valid until Y"
         ┌───────────────────────┼─────────────────────────────┐
         ▼                       ▼                             ▼
 ┌───────────────┐   ┌───────────────────────────┐   ┌─────────────────────────────┐
 │ YUBIKEY 5     │   │ DEVICE (UNO Q, STM32 side)│   │ GUARDIAN (Vultr verifier)   │
 │ P-256 FIDO2   │   │ ML-DSA-65 signing key     │   │ public keys + certificates  │
 │ credential    │   │  ◄ unlocked by YubiKey    │   │ seal chain (to open boxes)  │
 │ hmac-secret   │   │    hmac-secret + PIN +    │   │ ML-KEM/X25519 key           │
 │ (one per      │   │    device-unique secret   │   │ transparency-log key        │
 │  person)      │   │ seal chain K_i (ratchets) │   │ CAN'T sign approvals        │
 └───────────────┘   │ counter, lockout counter  │   └─────────────────────────────┘
                     └───────────────────────────┘
```

**Rules that make this hierarchy safe:**

- **One signing key per device, not a "real" key and a "decoy" key.** See [The decoy nobody can spot](#the-decoy-nobody-can-spot).
- **The signing key exists only while unlocked.** On disk it is encrypted twice over, and opening it needs three things at once: the YubiKey's hmac-secret (needs a touch), the PIN, and a device secret that never leaves the board (on the STM32 it is wrapped by the chip's own hardware unique key, DHUK, in its side-channel-resistant AES unit).
- **The guardian can refuse but never approve.** It holds only public keys, so it can't make the person's two signatures. If it is hacked, the worst it can do is block or leak alarms, not move money.
- **The root is offline and hash-based.** It's used a few times a year, so SLH-DSA's slowness doesn't matter, and its security doesn't depend on any newer maths.

## Enrolment: the one-time ceremony

Done once per person, in person, with a second team member watching.

1. **Create the org root** (once for the team) on a laptop with Wi-Fi off. Save it to the microSD, split a backup into 3 shares (any 2 rebuild it), and give the shares to 3 people.
2. **Register the YubiKey** with `attestation="direct"`. The device checks the attestation certificate chains to Yubico's root, so a fake "YubiKey" emulated by malware can't enrol. Record its public key and model ID (AAGUID).
3. **Set two PINs** on the Modulino Buttons: the normal one and the secret duress one. Use at least 8 presses (6,561 combinations with 3 buttons).
4. **Create the device key.** The STM32's true random number generator makes a 32-byte seed; the ML-DSA-65 key is computed from it. One YubiKey touch returns two hmac-secrets (one per PIN). The seed is wrapped once under each, in random order. **No PIN hash is stored anywhere.**
5. **Agree the sealing key** with the guardian using hybrid ML-KEM-768 + X25519 (`seal_root_device_side` in the code). Both sides now hold K₀.
6. **Record a one-minute calm baseline** of sensor readings (stored in Tiger Data, as already planned).
7. **The org root signs a membership certificate:** person, YubiKey public key, device public key, device ID, spending limits, expiry. The guardian only trusts approvals that chain to the root.

**Why fold the PIN into the YubiKey?** If someone copies the key file, every PIN guess needs a fresh physical touch on the real YubiKey *and* the device secret, which never leaves the board. Guessing offline is impossible; guessing on the device hits the lockout counter.

## How one approval works

```
 Requester (laptop / server / AI agent)        YuDuino (UNO Q)                         Guardian (Vultr)
 ──────────────────────────────────────        ───────────────                         ────────────────
 1. asks guardian for a nonce  ─────────────────────────────────────────────────────►  one-time nonce
 2. sends raw request + nonce ──────────►  3. STM32 parses the raw request itself,
                                              builds the display text, refuses
                                              anything it can't show in full.
                                              LED matrix: "PAY 10 GBP TO ..A1F3  K7QD"
                                              (K7QD = check code, also on big screen)
                                           4. User holds grip, enters PIN on buttons
                                              (sensors capture the 8-second window)
                                           5. User touches YubiKey: it signs
                                              SHA-256(core) ← what was shown
                                           6. Unlock: PIN → hmac-secret → which wrap
                                              opens = normal or duress mode
                                           7. Gemini verdict (fail closed) + onboard veto
                                              STM32 decides: normal / step-up / duress
                                           8. Seal status in a fixed-size AES box (K_i),
                                              ratchet K_i → K_{i+1}, erase K_i
                                           9. ML-DSA-65 signs core + YubiKey sig +
                                              box + previous log hash
                                          10. Append to hash-chained audit log
                       envelope ◄──────── LED shows "OK" (same in every mode)
 11. forwards envelope ─────────────────────────────────────────────────────────────►  12. verify everything
                                                                                       13. open the box
     "accepted" ◄──────────────────────────────────────────────────────────────────── normal: execute
     "accepted" ◄──────────────────────────────────────────────────────────────────── duress: HOLD + silent alert
     "need second approver" ◄──────────────────────────────────────────────────────── step-up
```

### What the guardian checks (step 12), all of them, every time

| Check | Stops |
|---|---|
| Suite is `YS1`, service ID is ours | Downgrades; relaying an approval to another service |
| Request hash matches the request it is about to run | Swapping the destination or amount after approval |
| Display hash matches the guardian's own rendering of that request | The device being tricked into showing something else |
| Nonce was issued by us and unused; not expired (2 min) | Replays; approvals saved up for later |
| YubiKey assertion: right key, right challenge, user-present flag set | Approvals without a physical touch by the named person |
| ML-DSA-65 signature from the device named in the certificate | Forgery (including by quantum computer); mixing parts of envelopes |
| Sealed box opens at the expected counter | Replays; stale or forged status |

### The envelope

```json
{
  "core":   {"v":1, "suite":"YS1", "type":"transfer", "rp":"guardian.yuduino.local",
             "who":"jonah", "device":"unoq-1",
             "request":"<SHA-256 of raw request>", "display":"<SHA-256 of text shown>",
             "nonce":"<from guardian>", "exp":1763150000},
  "yk":     {"authenticator_data":"…", "client_data_json":"…", "signature":"…"},
  "sealed": {"ctr":42, "box":"<12-byte nonce + AES-GCM of 512 padded bytes>"},
  "prev":   "<hash of previous audit log entry>",
  "pq_sig": "<ML-DSA-65 over core + YubiKey sig + sealed + prev>"
}
```

**Why the YubiKey signs only `core`:** the touch happens before Gemini's verdict exists, so the YubiKey can't sign the status. The ML-DSA signature then binds the YubiKey's signature, the status box and the log position together. Taking any part out of one envelope and putting it in another breaks the ML-DSA signature (there's a test for exactly this).

## The decoy nobody can spot

This is the open decision "fake approval design details" in the overview.

**The current code has a weakness.** [`pq_keystore.py`](../app/python/pq_keystore.py) makes two key pairs, "normal" and "duress", and [`verifier.py`](../app/python/verifier.py) tries one public key, then the other. Public keys aren't secret. Anyone who has them (a wallet contract, a log, a curious attacker) can check which key verifies and instantly know the alarm went off. On a blockchain the two keys would even be two different addresses.

**YuSeal's fix: one key, a sealed status.** Every approval is signed by the same ML-DSA key. The status lives inside an encrypted box that:

- is **always the same size** (512 bytes, padded with random bytes), whatever it holds;
- uses **AES-256-GCM**, so without the key, a normal box and a duress box are indistinguishable;
- is **bound to this approval** (the approval's hash is its associated data) and **covered by the ML-DSA signature**, so it can't be swapped;
- carries the features and Gemini verdict, so the guardian can **get a second opinion** (see below).

**Forward secrecy, which protects the victim afterwards.** The sealing key moves forward after every approval (K_{i+1} = HKDF(K_i)) and the old key is erased. If the attacker takes the device away and breaks into it later, they can't open earlier boxes, so they **can't prove you raised the alarm**. That matters if the attacker might retaliate.

**Same behaviour on every path.** The device always tries both PIN wraps, always calls Gemini, always seals, always signs, and the LED matrix shows the same "OK". The guardian's public answer is "accepted" for both. Large normal transfers also sit in a short release queue, so a held duress transfer doesn't stand out by not moving straight away.

**The hidden status is decided only on the STM32**, by one rule (`decide_status` in the code):

| Input | Result |
|---|---|
| Duress PIN, or an onboard veto (sensor unplugged, extreme reading) | Duress |
| Gemini says duress, or score ≥ 0.7 | Duress |
| Gemini silent, late, malformed, or score out of range | **Duress (fail closed)** |
| Score 0.4 to 0.7 | Step-up: second approver needed |
| Otherwise | Normal |

Gemini can raise the alarm but never lower it. A false alarm costs a short delay and a second approver, so failing closed is cheap.

**Guardian second opinion (Wave 3).** Because the box carries the features Gemini saw, the guardian can ask Gemini again on its own. If either says duress, it's duress. This covers a compromised Linux side that lies "all calm" to the STM32.

## The login system

Logins use the **same envelope** with `type: "login"`, so there's one thing to build and one thing to verify.

1. A service (the Vultr admin dashboard, an internal tool, the wallet console) shows a login challenge.
2. YuDuino's LED matrix shows `LOGIN dashboard AS jonah` and the check code; PIN, grip, touch.
3. The guardian verifies the envelope and issues a **10-minute session that is bound to the laptop's own key** (proof of possession, like DPoP), not a bearer token. Copying the session cookie to another machine does nothing.
4. **Sessions can look but not move.** Anything that changes money, permissions, deployments or delegations needs a fresh envelope for that exact action, even inside a session.
5. **Duress at login opens a honeypot session:** it looks real and shows plausible data, but it is read-only, every click is logged, and the alert goes out.

**This is the Binance lesson.** Attackers there used a stolen container deploy token, a long-lived credential anyone could copy. In YuDuino, nothing long-lived can authorise anything: every dangerous action needs a fresh, touch-bound, transaction-bound signature.

**Also covered:**

- **Phishing and relaying.** The envelope names the service (`rp`), and the YubiKey assertion is tied to the service ID, so an approval collected by a fake site can't be used on the real one.
- **AI agents never hold keys.** An agent files a request, and a named human approves it on the device. The audit log records both the agent that asked and the human who approved.
- **SSH (future):** after an envelope, the guardian issues a 10-minute SSH certificate. OpenSSH 10 already uses the hybrid post-quantum key exchange (`mlkem768x25519-sha256`) by default.

## What you see is what you sign

- **The STM32 drives the LED matrix** (the Arduino docs confirm it is managed by the microcontroller, not Linux). That makes it the most trusted output on the board.
- **The device parses the raw request**; the laptop's description is ignored. Unknown fields or actions are refused, and anything too long to show in full is refused rather than cut short.
- **A 4-character check code** (from the approval's hash) appears on both the LED matrix and any big screen driven by Linux. If they differ, the big screen is lying.
- **Danger actions get a `!` and a second approver:** EIP-7702 delegations, unlimited token approvals, adding signers, changing policies, deploying to the signing service. These are exactly what was abused on 29 October.
- **Big actions need 2 of 3 people**, each with their own device and YubiKey, plus a time lock.

## The audit trail: who authorised what

1. **On the device:** each envelope adds a log entry holding the previous entry's hash, signed with ML-DSA. Edit, delete or reorder one entry and the chain breaks (tested). A copy goes to the microSD.
2. **On the guardian:** entries go into a **transparency log**, a Merkle tree like the one behind HTTPS Certificate Transparency. The guardian signs the tree head. Each device checks the guardian keeps adding to the same tree (it can't show different histories to different people).
3. **Daily checkpoint:** the tree head is signed with the SLH-DSA root and, as a Solana stretch goal, posted on chain, so even the guardian's own admins can't rewrite history.
4. **Tiger Data** stores one row per approval with the entry hash, so the dashboard can show the chain and check it on load.

The public log stores the sealed box, never the plain status, so reading the log doesn't reveal alarms. The guardian's incident records (for admins) do.

**"Who approved it?"** is answered by: approver name → membership certificate (signed by the root) → genuine YubiKey (attestation) → touch on this exact request (assertion) → this device (ML-DSA) → this place in history (log).

## Recovery and revocation

- **Lost YubiKey:** enrol two YubiKeys from day one (the second lives in a safe). The seed is wrapped under each.
- **Lost or broken device: don't back up signing keys; replace them.** Signing keys, unlike encryption keys, don't need to be recovered: enrol a new device, have the root sign a new certificate, and revoke the old one. That needs 2 of 3 people and a 24-hour delay with alerts to everyone, so an attacker can't "recover" their way in quietly.
- **Revocation list:** signed by the root and checked by the guardian on every approval.
- **Lost root:** any 2 of the 3 backup shares rebuild it (Shamir secret sharing).
- **Too many wrong PINs** (5): the device locks and needs a guardian unlock plus a second approver.

## The network

- **Hybrid post-quantum TLS** (X25519MLKEM768) to Gemini and the guardian. OpenSSL 3.5 and newer offers it by default; check `openssl version` on the UNO Q. This stops "harvest now, decrypt later" of the features and frames sent to Gemini.
- **Pinning:** the guardian's own certificate is pinned exactly. For Google, pin the Google Trust Services root CAs rather than the server certificate, which rotates often.
- **Envelopes don't depend on TLS.** They are signed end to end, so even a broken TLS connection can't forge or change an approval.

## Threat coverage

| Attack | What stops it |
|---|---|
| Malware on the laptop fakes "approved" | No "OK" message exists; only signed envelopes count |
| Laptop swaps the destination after you approve | Request hash in `core`; guardian recomputes it |
| Laptop shows you a different transaction | Device parses raw bytes itself; check code on the LED matrix |
| Stolen session token or deploy token (Binance) | Sessions are short, key-bound and can't move money; every action needs a fresh envelope |
| Signing service driven directly (Binance) | The guardian is the only route to execute and requires an envelope per action |
| EIP-7702 delegation abuse (Binance) | Danger action: `!DELEGATE`, second approver, time lock |
| Replaying an old approval | Nonce, expiry and ratchet counter |
| Stolen YubiKey | Also needs the PIN and the device |
| Stolen device | Also needs the YubiKey and PIN; device secret can't be extracted by software |
| Copied key file, offline PIN guessing | Each guess needs a YubiKey touch and the device secret |
| Someone forces you to approve | Duress PIN or Gemini's verdict → sealed duress → hold and silent alert |
| Attacker checks which key signed | Only one key; status hidden in a same-size encrypted box |
| Attacker seizes the device afterwards to see if you raised the alarm | Ratchet: old sealing keys are erased |
| Network down or Gemini blocked to force a "calm" result | Fail closed: no verdict means duress |
| Fake Gemini on the network | Pinned TLS; the verdict can only raise the alarm anyway |
| Compromised Linux side says "calm" | Guardian second opinion from the sealed features; onboard veto |
| Future quantum computer forges signatures | ML-DSA required alongside the YubiKey; SLH-DSA roots |
| Harvest now, decrypt later | Hybrid ML-KEM TLS; ML-KEM for the sealing key |
| Insider edits the audit log | Hash chain, device signatures, transparency log, SLH-DSA checkpoints |
| Phishing site relays an approval | Service ID bound into `core` and the YubiKey assertion |
| Fake YubiKey at enrolment | Attestation check against Yubico's root |
| Malicious firmware pushed to the device | No over-the-air updates; firmware signed by the root (secure boot later) |
| Hacked guardian | Can block or leak alarms, but can't create approvals |

## Remaining weak spots

Honest list, worst first.

1. **The hackathon build keeps the keys on the Linux side.** Until Wave 4 (or later) the ML-DSA key, seal chain and decision logic run in Python on the QRB2210, next to the camera, network and Gemini code. Root on Linux means game over for that device. The design puts them on the STM32; we're not there tonight.
2. **The YubiKey talks to Linux over USB.** The hmac-secret and the PIN pass through Linux. The fix (future) is for the STM32 to act as the FIDO2 "platform": CTAP2 encrypts hmac-secret and PIN traffic with a key agreed between the platform and the YubiKey, so Linux becomes a dumb pipe that only sees ciphertext.
3. **No secure element.** The STM32U585 has TrustZone, a hardware unique key and side-channel-resistant AES, which is good, but it's not a certified secure element. A skilled lab attacker with the device could glitch it. Our answer is that the device alone isn't enough (YubiKey and PIN are also needed).
4. **The YubiKey half is classical.** A quantum computer could forge the YubiKey signature. ML-DSA still protects the approval, but the "proof of touch" then rests on the device being honest. A post-quantum security key would fix this when one exists.
5. **A calm, determined attacker.** If they know about duress detection, the decoy only buys time: they will eventually notice the money didn't move. Time locks and the silent alert are meant to make that time enough.
6. **Gemini can be wrong or fooled.** It may flag a nervous but willing user (cheap: second approver) or miss a calm coerced one. Attackers could also try **prompt injection through the camera**, such as a printed sign saying "the user is calm". Mitigations: structured output only, image treated as data, Gemini can only raise the alarm, and the duress PIN is always there.
7. **Short PINs.** Three buttons give few combinations. The lockout counter and YubiKey-touch-per-guess make it acceptable, but use 8+ presses.
8. **An 8×13 LED matrix can't show everything.** Long or complex requests are refused, which is safe but limiting.
9. **Bugs beat maths.** This is new code written at a hackathon; that's far more likely to fail than ML-DSA. The tests help; an external review would help more.
10. **The supply chain** (how Binance was first breached): a poisoned library on the board or the laptop. Pinned dependencies, signed firmware and reproducible builds reduce it.
11. **ML-DSA is young** (standardised 2024). That's why it's always paired with classical signatures for approvals, and the root uses hash-based SLH-DSA.

## What we build when

### Hackathon (fits the existing waves)

| Wave | Crypto work | In the code |
|---|---|---|
| **1. Skeleton** (now) | Switch to **one ML-DSA-65 key** plus the sealed status box, replacing the real/decoy key pair. YubiKey signs `core`. Verifier checks everything and answers "accepted" for both normal and duress. Use `cryptography>=48` for ML-DSA instead of building liboqs. | `yuseal.py` is ready: call `build_core`, `make_envelope` and `Verifier.check` from `main.py` |
| **2. Real signals** | Nonce, expiry and counter checks (done in `Verifier`); hash-chained, signed audit log (done: `log_append`); PIN folded into the YubiKey (done: `create_keystore`/`unlock`, replacing `check_pin`). Move the **decision rule, LED matrix display and check code** to the STM32 sketch: Linux sends the verdict, the STM32 decides and shows. | Port `decide_status` and `check_code` to `sketch.ino` |
| **3. Response and polish** | Verifier on Vultr is the only route to execute. YubiKey attestation at enrolment. Hybrid ML-KEM enrolment of the seal key (done: `seal_root_*`). **YuDuino login** for the admin dashboard, with the honeypot session on duress. Guardian second opinion. Merkle tree head on the dashboard. | `merkle_root` is ready |
| **4. Harden and stretch** | ML-DSA on the STM32 if time (C library such as mldsa-native or PQClean; ~80 KB RAM, fine on 786 KB). SLH-DSA-signed membership certificates and checkpoints. Check hybrid TLS is negotiated. Solana: post the daily tree head on devnet. | |

### After the hackathon

- **STM32 as the FIDO2 platform**, so Linux only relays encrypted CTAP2 traffic.
- **DHUK + SAES key wrapping, TrustZone (TF-M) and secure boot** on the STM32U585, with the debug port locked.
- **A certified secure element** in the next hardware version.
- **Multi-person threshold signing**, so a big action needs a signature only 2 of 3 devices can make together (post-quantum threshold schemes are still research; today we use 2 of 3 separate envelopes).
- **A local model** (such as Gemma) on the Linux side, so no features leave the device.
- **Public witnesses** that co-sign the transparency log, and reproducible firmware builds.
- **A formal model** of the protocol in a tool like Tamarin or ProVerif, plus an external audit.
- **Post-quantum security keys** when they ship, to make the presence proof quantum-safe too.

## Glossary

- **Signature:** proof that a specific private key approved specific bytes. Anyone with the public key can check it; nobody without the private key can make it.
- **Hash:** a fingerprint of data. Change one bit and the fingerprint changes completely.
- **ML-DSA / SLH-DSA / ML-KEM:** NIST's post-quantum standards (2024): a lattice signature, a hash-based signature and a key-agreement method.
- **Hybrid:** using a classical and a post-quantum algorithm together, so you're safe if either holds.
- **Nonce:** a number used once, so an old message can't be replayed.
- **Ratchet:** a key that turns into the next key one way only; you can go forward, never back.
- **Forward secrecy:** stealing today's key doesn't unlock yesterday's messages.
- **Attestation:** a certificate built into the YubiKey at the factory that proves it's genuine.
- **Transparency log:** an append-only log anyone can check hasn't been rewritten.
- **Fail closed:** when in doubt, do the safe thing (here: hold and alert).
