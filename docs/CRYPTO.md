# YuDuino cryptography: the YuSeal design (v2)

*Version 2, written 14 November 2026, evening of day one of DurHack. It replaces the first version, which had seven gaps (listed in the [design brief](DESIGN-BRIEF.md#6-review-of-v1-against-this-brief)).* Back to the **[overview](YuDuino-Overview.md)** · **[build flow](BUILD-FLOW.md)** (what to code where) · **[dev plan](DEV-PLAN.md)** · **[hardware plan](HARDWARE-PLAN.md)**

> **Final design: mouse mode (v3), as presented at DurHack.** Solana and ElevenLabs below were never built.
>
> **Mouse mode (design change, 2026-11-14).** This page was written for **v2 (a PIN on buttons and the request text on the LED matrix)**. The code now implements **v3, mouse mode** (suite `YS3`), because the device lives **inside a normal-working mouse with no screen, no PIN and no extra input**. In that mode the three proofs, the ML-DSA seal, the audit log, the nonces and the verifier's checks are **unchanged**, but:
> - the **STM32 tag** binds the status, the request digest, **a physical click** (its age and whether the palm was on the grip) and **a hash of the attested sensor summary**, instead of the PIN and the displayed text;
> - there is **no trusted display** and **no PIN or duress PIN**; duress is detected **only passively, and only at the moment of a transaction**;
> - the YubiKey is used **without a touch**, except for step-up;
> - the verifier recomputes an **owner check** from the attested features, and quietly rejects other hands.
>
> Full design, and what protection this gives up: **[STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)** and **[OWNER-CHECK.md](OWNER-CHECK.md)**. The new weak spots are items 15 to 20 below. Everything in this file that mentions a PIN, the matrix or "what you see is what you sign" describes the earlier v2 and is no longer in the code (git commit `2c455f8`). The v3 tag is `HMAC(K_TAG, "YS3/tag" | status | request digest | click_age (2 bytes) | grip (1 byte) | SHA-256("YS3/features" | ten big-endian int32))`.

Working code, all tested (`cd app/python && python3 -m unittest test_yuseal -v`, 41 tests):

| File | What it is |
|---|---|
| [`app/sketch/yuseal_mcu.h`](../app/sketch/yuseal_mcu.h) | The trusted core that runs on the STM32. SHA-256 and HMAC only, about 1 KB of RAM. Compiled and tested on a laptop against the Python model |
| [`app/python/yuseal.py`](../app/python/yuseal.py) | The envelope, the verifier's checks, key store, audit log. Also `SoftMcu`, a Python twin of the STM32 code |
| [`app/python/approve.py`](../app/python/approve.py) | The Linux side of one approval, and of enrolment |
| [`app/python/verify_cli.py`](../app/python/verify_cli.py) | A tiny reference verifier for trying it; the customer calls `Verifier` from their own system |
| [`tools/provision.py`](../tools/provision.py) | One-off tool that makes the STM32's secrets |

It needs only `cryptography>=48`, which has ML-DSA built in, so **no liboqs build on the board**.

## In one minute

Every approval is a sealed envelope that carries **three independent proofs**, made by three different things:

| Proof | Made by | Says | Hard for malware on Linux because |
|---|---|---|---|
| **YubiKey signature** | The YubiKey, on a physical touch | "This named person's key signed this exact request" | The private key never leaves the chip |
| **STM32 tag** | The microcontroller, after a correct PIN on the real buttons | "A person pressed the PIN for exactly the text on the LED matrix", and secretly "normal", "step-up" or "duress" | The PIN never leaves the STM32, and Linux can't make or read a tag |
| **ML-DSA signature** | The Linux side, with a key unlocked by the YubiKey and the STM32 | "I, this device, seal all of the above, in this place in the log", safe against quantum computers | Needs the YubiKey, the STM32's salt and a touch |

The customer's verifier checks all three. An attacker who gets two of them still can't approve.

The **tag is the new idea in v2.** It is the only thing that proves the buttons were pressed and the display showed this request, and it is made with nothing but SHA-256, so it is small enough to trust, tested line by line, and quantum-safe already.

## What "unbreakable" honestly means here

Nothing is unbreakable. What we can do is make sure that:

- **No single stolen thing is enough, and no single compromised computer is enough.** Even root on the Linux side can't make an approval, because it can't make the STM32's tag.
- **The maths has independent locks.** A forger must break the YubiKey's P-256, ML-DSA-65 (lattices) and HMAC-SHA-256 (hashes). Long-lived roots use SLH-DSA, which depends only on SHA-256.
- **When something breaks, it fails safe and leaves evidence.** Missing, late or strange inputs mean hold and alert, never approve. Every decision goes in a log that can't be edited without it showing.

The remaining weak spots are listed in [Remaining weak spots](#remaining-weak-spots), worst first. Attackers go for bugs, people and supply chains long before they attack the maths, so most of this design is about those.

## The building blocks

| Block | What it does for us | Why this one | Safe against quantum? |
|---|---|---|---|
| **HMAC-SHA-256** | The STM32's PIN check and tag; the verifier re-checks the tag | Needs only SHA-256 (the STM32 has a hardware accelerator); 100 lines of C++; no big numbers | Yes |
| **ML-DSA-65** (FIPS 204, 2024) | Seals every envelope and log entry | NIST's main post-quantum signature; 3,309-byte signatures | Yes |
| **SLH-DSA-SHA2-128s** (FIPS 205) | Org root: membership certificates, firmware, daily checkpoints | Security rests only on SHA-256. Slow, so used rarely | Yes |
| **YubiKey 5 FIDO2, ES256 (P-256)** | Proves a named person touched a genuine YubiKey for *this* request | Key can't leave the chip; attestation proves it's genuine | No, which is why it never stands alone |
| **YubiKey hmac-secret** | Unlocks the ML-DSA key (together with the STM32's salt) | Only that YubiKey can produce it, only on touch | Yes (symmetric) |
| **AES-256-GCM** | The key wrap (the ML-DSA key on the board) | 256-bit keys stay strong against Grover's algorithm | Yes |
| **HKDF-SHA-256** | Turns the YubiKey secret into the wrap key | Standard key derivation | Yes |
| **SHA-256** | Every hash: request, display, log, Merkle tree | 128-bit security even against quantum search | Yes |

Every envelope names its suite (`YS2`), so we can swap algorithms later without changing the format (**crypto-agility**).

## Who holds what: the key hierarchy

```
                 ┌───────────────────────────────────────────┐
                 │ ORG ROOT  (SLH-DSA, hash-based)           │  offline: created once on an
                 │ signs membership certs,     │  unplugged laptop, kept on the
                 │ firmware, revocations, checkpoints        │  microSD; backup split 2-of-3
                 └───────────────┬───────────────────────────┘
          membership certificate │ "Jonah = this YubiKey + this device key + this tag key, expiry"
         ┌───────────────────────┼──────────────────────────────┐
         ▼                       ▼                              ▼
 ┌───────────────┐   ┌─────────────────────────────┐   ┌─────────────────────────────┐
 │ YUBIKEY 5     │   │ DEVICE (UNO Q)              │   │ VERIFIER (customer's)   │
 │ P-256 FIDO2   │   │ ┌─────────────────────────┐ │   │ public keys + certificates  │
 │ credential    │   │ │ STM32 (trusted core)    │ │   │ tag key (checks STM32 tags) │
 │ hmac-secret   │   │ │ K_MCU → PIN key, tag key│ │   │ audit log + tree head       │
 │ (one per      │   │ │ PIN tags, lockout count │ │   │                              │
 │  person)      │   │ │ LED matrix, buttons     │ │   │ CAN'T sign approvals        │
 └───────────────┘   │ └─────────────────────────┘ │   └─────────────────────────────┘
                     │ ┌─────────────────────────┐ │
                     │ │ Linux                   │ │
                     │ │ ML-DSA key, wrapped:    │ │
                     │ │  YubiKey secret(salt)   │ │
                     │ │  salt = STM32 after PIN │ │
                     │ │ audit log               │ │
                     │ └─────────────────────────┘ │
                     └─────────────────────────────┘
```

**Rules that make this hierarchy safe:**

- **One ML-DSA key per device, not a "real" key and a "decoy" key.** See [The decoy nobody can spot](#the-decoy-nobody-can-spot).
- **The PIN lives on the STM32 and nowhere else.** The buttons are wired to it, not to Linux. Linux never sees a press, only "state" and "number of presses so far".
- **The ML-DSA key needs two locks.** It is wrapped under the YubiKey's hmac-secret for a salt that **only the STM32 releases, and only after a correct PIN**. There is no PIN hash on Linux to guess offline, and the wrong-PIN lockout can't be bypassed from Linux.
- **The verifier can refuse but never approve.** It holds public keys and the tag key, which can't make the YubiKey or ML-DSA signatures.
- **The root is offline and hash-based.** It's used a few times a year, so SLH-DSA's slowness doesn't matter.

## The STM32's trusted core

The whole security argument depends on this one small piece, so it is built to be checked by hand. It lives in [`yuseal_mcu.h`](../app/sketch/yuseal_mcu.h) and does five things:

1. **`begin(text, digest)`**: Linux hands over the text to show and the approval's digest. The STM32 **hashes the text itself**, checks it is plain printable characters under 97 long, shows it, and starts waiting for a PIN.
2. **Counts button presses**, but only while the grip sensor says the grip is held. A **short press** is a capital letter (`A`), a press **held 0.8 s or more** is a lowercase letter (`a`).
3. **After the last press plus 1.5 s**, checks the PIN by computing `HMAC(K_PIN, "pin|" + presses)` and comparing it, in constant time, with **both** stored tags (normal and duress). Wrong: count it, and after 5 wrong the device locks. Either right: the same thing happens, so **Linux can't tell which PIN was used**.
4. **`unlockSalt()`**: after a correct PIN, releases `HMAC(K_PIN, "unlock-salt")`. This lets Linux unwrap the ML-DSA key with the YubiKey.
5. **`seal(score, veto)`**: takes the model's score as a whole number 0 to 100 (anything else counts as "no verdict"), decides the status, and returns the tag `HMAC(K_TAG, "YS2/tag" + status + SHA256(text) + digest)`. **It works once per `begin()`.**

**The decision rule** (the same in C++ and Python, checked against each other for every case):

| Input | Status |
|---|---|
| Duress PIN, or an onboard veto (sensor unplugged, impossible readings) | Duress |
| Score missing, below 0, above 100, not a whole number | **Duress (fail closed)** |
| Score 70 to 100 | Duress |
| Score 40 to 69 | Step-up |
| Score 0 to 39 | Normal |

The model can raise the alarm but never lower it. A false alarm costs a short delay, so failing closed is cheap.

**What this buys:** a tag exists only if a person pressed the right PIN, on these buttons, with the grip held, **for the exact text that was on the LED matrix**, and the digest is tied to it. Malware on Linux can't make a tag for anything else, can't reuse one (it covers the display hash and digest), and can't read the status inside it.

## Enrolment: the one-time ceremony

Done once per person, in person, with a second team member watching.

1. **Create the org root** (once for the team) on a laptop with Wi-Fi off. Save it to the microSD, split a backup into 3 shares (any 2 rebuild it), and give the shares to 3 people.
2. **Pick two PINs** of 8 to 12 presses over `A B C` (short) and `a b c` (long press). That is 6⁸ = 1.7 million to 6¹² = 2 billion possibilities. The **duress PIN should differ from the normal one by one press's length**: same buttons, one held longer. Someone watching you type can't easily tell which you entered.
3. **Run `tools/provision.py`** on a laptop. It makes `K_MCU` (32 random bytes), computes the two PIN tags, and writes `secrets.h` for the sketch and a key file for the verifier. Flash the sketch, then delete the files that shouldn't live on.
4. **Register the YubiKey** (`attestation="direct"`, so a fake "YubiKey" emulated by malware can't enrol).
5. **Enter the normal PIN once.** The STM32 releases the salt, the YubiKey gives its hmac-secret for it, and the ML-DSA-65 key is made and wrapped under it.
6. **Record a one-minute calm baseline** of sensor readings (stored on the device).
7. **The org root signs a membership certificate** (Wave 3): person, YubiKey public key, ML-DSA public key, tag key, expiry.

## How one approval works

```
 Requester                    Linux (UNO Q)               STM32 (UNO Q)         YubiKey       Verifier
 ─────────                    ─────────────               ─────────────         ───────       ────────
                              1 ask for nonce ───────────────────────────────────────────────►
                              ◄─────────────────────────────────────────────────── nonce
 2 raw request ─────────────► 3 build core {request hash, display hash, nonce, service, who}
                                 digest = SHA-256(core)
                              4 begin(text, digest) ────► 5 hash the text itself, show it:
                                                            "PAY 10 GBP TO ALICE"
                                                         6 person presses PIN, grip held
                                                         7 correct PIN → salt (same for both PINs)
                              ◄──────────── salt ───────
                              8 YubiKey: sign digest + hmac-secret(salt) ───────► touch
                              ◄───────────────────────────────────────── signature + secret
                              9 unwrap ML-DSA key; the on-device model on the sensor window
                              10 seal(score) ───────────► 11 decide status, make tag, LED: "OK"
                              ◄──────────── tag ────────
                              12 ML-DSA seal, log entry
 ◄──── "accepted" ◄────────── 13 envelope ───────────────────────────────────────────────────►
                                                                         14 check everything, read the tag
                                                       normal: execute · duress: hold + silent alert
```

### What the verifier checks, all of them, every time

| Check | Stops |
|---|---|
| Suite is `YS2`, service ID is ours | Downgrades; relaying an approval to another service |
| Request hash matches the request it is about to run | Swapping the destination or amount after approval |
| Display hash matches the verifier's **own** rendering of that request | A device (or Linux) showing something different from what's signed |
| Nonce was issued by us, unused, and under 2 minutes old (**our** clock) | Replays; approvals saved up for later. The device has no trusted clock, so it can't enforce expiry |
| YubiKey assertion: right key, right challenge, user-present flag | Approvals without a physical touch by the named person |
| ML-DSA-65 signature from the device named in the certificate | Forgery (including by quantum computer); mixing parts of envelopes |
| **The tag matches exactly one of normal / step-up / duress** | Anything the STM32 didn't produce: no PIN pressed, wrong display, wrong request |

Then the verifier may **only make the outcome stricter**. It can turn "normal" into "step-up", never the other way round.

### The envelope

```json
{
  "core":   {"v":2, "suite":"YS2", "type":"transfer", "rp":"yuduino.local",
             "who":"jonah", "device":"unoq-1",
             "request":"<SHA-256 of raw request>", "display":"<SHA-256 of text shown>",
             "nonce":"<from verifier>"},
  "yk":     {"authenticator_data":"…", "client_data_json":"…", "signature":"…"},
  "mcu":    "<32-byte HMAC tag from the STM32>",
  "prev":   "<hash of previous audit log entry>",
  "pq_sig": "<ML-DSA-65 over core + YubiKey sig + tag + prev>"
}
```

Taking any part out of one envelope and putting it in another breaks the ML-DSA signature, or the tag, or the YubiKey signature (there are tests for each).

## The decoy nobody can spot

The overview's open decision, "fake approval design details", is settled like this.

**What was wrong:** the original code in `pq_keystore.py` made two key pairs, "normal" and "duress", and `verifier.py` tried one public key, then the other. Public keys aren't secret, so anyone holding them (a wallet contract, a log, a curious attacker) can check which key verified and instantly know the alarm went off.

**YuSeal's answer: one key, and the status is inside the STM32's tag.**

- Every approval is signed by the same ML-DSA key and the same YubiKey. Nothing visible differs.
- The status is mixed into the **tag**, which is an HMAC: without the verifier's tag key, a normal tag and a duress tag are indistinguishable 32 random-looking bytes. Only the verifier can try the three statuses and see which matches.
- **Linux never learns the status.** It never sees the PIN, only a salt that is the same for both PINs. It passes the model's number in and gets a tag out. So malware on the board can't tip off an attacker, and can't be made to.
- **Same behaviour on every path.** The LED matrix shows `OK` for normal and duress alike, the envelope has the same shape and size, and the verifier answers the requester `accepted` for both. A held transfer sits in the same short queue as a normal large one.
- **The duress PIN looks the same to an observer.** It uses the same buttons as the normal PIN, with one press held longer. (If they know the exact timing pattern of your normal PIN they'd notice. Use a hood over the buttons, [weak spot 6](#remaining-weak-spots).)

**Nothing about the alarm is stored on the device.** The model's score is passed to the STM32 and then forgotten. The tag can't be read without the tag key, which is not on the device's Linux side, so a seized device can't show which approvals raised the alarm.

**Dropped for the hackathon:** an encrypted "evidence box" with a hybrid ML-KEM + X25519 key agreement, which let the verifier ask a second model for a second opinion. The gap this leaves is a compromised Linux side telling the STM32 "all calm"; the onboard veto and the duress PIN still cover it (weak spot 14). It can come back after the hackathon.

## The login system

Logins use the **same envelope** with `type: "login"`, so there's one thing to build and one thing to verify.

1. A service (an internal dashboard, a tool, the wallet console) shows a login challenge.
2. The LED matrix shows `LOGIN DASHBOARD AS JONAH`; PIN, grip, touch.
3. The verifier verifies the envelope and issues a **10-minute session that is bound to the laptop's own key** (proof of possession), not a bearer token. Copying the session cookie to another machine does nothing.
4. **Sessions can look but not move.** Anything that changes money, permissions, deployments or delegations needs a fresh envelope for that exact action, even inside a session.
5. **Duress at login opens a honeypot session:** it looks real and shows plausible data, but it is read-only, every click is logged, and the alert goes out.

**This is the Binance lesson.** Attackers there used a stolen container deploy token, a long-lived credential anyone could copy. In YuDuino, nothing long-lived can authorise anything: every dangerous action needs a fresh, touch-bound, transaction-bound envelope.

**Also covered:**

- **Phishing and relaying.** The envelope names the service (`rp`), and the YubiKey assertion is tied to the service ID, so an approval collected by a fake site can't be used on the real one.
- **AI agents never hold keys.** An agent files a request, and a named human approves it on the device. The audit log records both.
- **SSH (future):** after an envelope, the verifier issues a 10-minute SSH certificate. OpenSSH 10 already uses the hybrid post-quantum key exchange (`mlkem768x25519-sha256`) by default.

## The audit trail: who authorised what

1. **On the device:** each envelope adds a log entry holding the previous entry's hash, signed with ML-DSA. Edit, delete or reorder one entry and the chain breaks (tested). A copy goes to the microSD.
2. **On the verifier:** entries go into a **transparency log**, a Merkle tree like the one behind HTTPS Certificate Transparency. The verifier signs the tree head, so it can't show different histories to different people.
3. **Daily checkpoint:** the tree head is signed with the SLH-DSA root and, as a Solana stretch goal, posted on chain, so even the verifier's own admins can't rewrite history.
4. **The local store** keeps one row per approval with the entry hash, so the dashboard can show the chain and check it on load.

The log stores a hash of the envelope, never the plain status, so reading it doesn't reveal alarms. The verifier's incident records (for admins) do.

**"Who approved it?"** is answered by: approver name → membership certificate (signed by the root) → genuine YubiKey (attestation) → touch on this exact request (assertion) → buttons and display on this device (tag) → this device (ML-DSA) → this place in history (log).

## Failure modes

Every row has a defined, safe result. Each is tested unless marked.

| What happens | Result |
|---|---|
| Wrong PIN | Nothing released. After 5 wrong, the STM32 locks until power-cycled |
| Grip not held | Presses don't count; the request times out after 90 s |
| Model missing, faulty or malformed | No score, so **duress**. Approval completes, the verifier holds it and alerts |
| Wi-Fi down | Linux can't reach the verifier: nothing executes. The envelope is kept and sent when back; its nonce will have expired, so the person approves again (not tested) |
| Verifier down | Nothing executes (it is the only route). The device still makes decoys the same way |
| YubiKey unplugged or the wrong one | Can't unwrap the ML-DSA key; refused |
| Power cut mid-approval | STM32 forgets the session (RAM). The next `begin` starts clean. Linux's state file is written atomically |
| Bridge call fails or is called out of order | The STM32 core returns "-" or "0"; there is no state in which a tag is made without a correct PIN (tested) |
| Linux calls `seal` twice, or after the timeout | The second call and any call after 90 s return nothing (tested) |
| A sensor is unplugged or reads impossibly | Onboard veto, so duress (tested) |

## Recovery and revocation

- **Lost YubiKey:** enrol two YubiKeys from day one (the second lives in a safe). In Wave 3, a second wrap of the ML-DSA key under the spare YubiKey.
- **Lost or broken device:** don't back up signing keys; replace them. Enrol a new device, have the root sign a new certificate, revoke the old one. That needs 2 of 3 people and a 24-hour delay with alerts to everyone, so an attacker can't "recover" their way in quietly.
- **Revocation list:** signed by the root and checked by the verifier on every approval.
- **Lost root:** any 2 of the 3 backup shares rebuild it (Shamir secret sharing).
- **Forgotten PIN:** the STM32 can't be unlocked. Re-provision and re-enrol with the root's approval.
- **Someone leaves the team:** revoke their certificate; their device stops working at the verifier immediately.

## The network

- **Hybrid post-quantum TLS** (X25519MLKEM768) to the verifier. OpenSSL 3.5 and newer offers it by default; check `openssl version` on the UNO Q. This stops "harvest now, decrypt later" of what is sent to the verifier.
- **Pinning:** the verifier's own certificate is pinned exactly.
- **Envelopes don't depend on TLS.** They are signed end to end, so even a broken TLS connection can't forge or change an approval.

## Privacy

- **Raw camera frames, audio and PINs never leave the board.** The Edge Impulse model runs on the board, so features and frames stay on it.
- **The model's verdict is not stored** on the device or the verifier: only the status inside the STM32's tag.
- **The local store** keeps scores per usage, not frames or audio.
- Reading emotion at work is restricted in the EU. The framing is *context risk scoring for consenting team members*, with the duress PIN as the main signal.
- **Accessibility:** ElevenLabs reads the **request text** aloud, never the status, so what is spoken is the same for normal and duress.

## Threat coverage

| Attack | What stops it |
|---|---|
| Malware on the laptop fakes "approved" | No "OK" message exists; only signed envelopes with a tag count |
| Laptop swaps the destination after you approve | Request hash in the envelope; the verifier recomputes it |
| **Root on the Linux side** waits for a real touch and swaps the request | The tag covers the display hash and digest of what the STM32 showed, so it doesn't fit the swapped request (tested twice) |
| Root on Linux makes the YubiKey sign and unwraps the ML-DSA key | Still needs a tag: needs the PIN on the buttons, for this exact text |
| Stolen session token or deploy token (Binance) | Sessions are short, key-bound and can't move money; every action needs a fresh envelope |
| Signing service driven directly (Binance) | The verifier is the only route to execute and requires an envelope per action |
| Replaying an old approval | Nonce, 2-minute expiry on the verifier's clock |
| Stolen YubiKey | Also needs the PIN and the device |
| Stolen device | Also needs the YubiKey; the tag key and K_MCU aren't on Linux |
| Someone forces you to approve | Duress PIN or the model's verdict → duress tag → hold and silent alert |
| Attacker checks which key signed | Only one key; status hidden in a tag only the verifier can read |
| Malware tips off the attacker | Linux never sees the PIN and gets the same salt and a same-size tag whichever PIN was used (tested) |
| Attacker seizes the device later to see if you raised the alarm | Nothing about it is stored; the tag key isn't on the device's Linux side |
| Linux tells the STM32 "calm" | Onboard veto and the duress PIN (a real gap: weak spot 14) |
| Future quantum computer forges signatures | ML-DSA required alongside the YubiKey; the tag is HMAC (not breakable by Shor); SLH-DSA roots |
| Harvest now, decrypt later | Hybrid ML-KEM TLS (a setting, if the board's OpenSSL is 3.5+); nothing sensitive is stored encrypted |
| Insider edits the audit log | Hash chain, device signatures, transparency log, SLH-DSA checkpoints |
| Phishing site relays an approval | Service name bound into the envelope and YubiKey signature |
| Fake YubiKey at enrolment | Attestation checked against Yubico's root |
| Malicious firmware | No over-the-air updates; root-signed firmware; secure boot later |
| Hacked verifier | Can block or leak alarms, but can't create YubiKey or ML-DSA signatures |

## Remaining weak spots

Honest list, worst first.

1. **PIN guessing with the device in hand.** The lockout counter lives in the STM32's RAM, so cutting power resets it. A thief with the device **and** the YubiKey could try PINs on the buttons (6⁸ = 1.7 million combinations at about 4 s a try, so months by hand, but a robot could do it faster). Fix: keep the counter in flash (VERIFY storage on the UNO Q), use 10+ presses, and have the verifier count failed attempts. A thief with only the device still can't make the YubiKey signature.
2. **`K_MCU` is in the STM32's flash.** Anyone who can read the chip's flash gets it, unless the debug port is locked (readout protection) and, later, secure boot and TrustZone are used. Until then, treat the board as sensitive.
3. **Keys on Linux tonight.** The ML-DSA key is on the Linux side while it signs. Root on Linux can use it, with a YubiKey touch and the salt, but **can't make a tag**, so the envelope is rejected. It also sees the sensors, so it can block or delay approvals (denial of service).
4. **The verifier's tag key.** An insider with it can make tags, but not YubiKey or ML-DSA signatures, so still not approvals. Keep it in an HSM later.
5. **The YubiKey half is classical.** A quantum attacker could forge the YubiKey signature. The ML-DSA signature and the HMAC tag still stand, so a forger would need the ML-DSA key (device) and a tag (PIN), but "who touched it" would rest on those. A post-quantum security key would fix this when one exists.
6. **Shoulder-surfing.** Someone who watches you type your normal PIN, including the timing, learns it. The duress PIN is meant to be indistinguishable *unless they know the timing*. The mouse shell helps: PIN presses look like ordinary clicks, and the keys are shielded by the hand ([MOUSE-DESIGN.md](MOUSE-DESIGN.md)).
7. **A calm, determined attacker.** If they know about duress detection, the decoy only buys time; they will eventually notice nothing moved. Time locks and the silent alert are meant to make that time enough.
8. **The model can be wrong or fooled.** It sees only numbers (no image goes to it), so there is no prompt injection, but a trained model can still be mistaken or tricked by someone who knows how it was trained. Mitigations: it can only raise the alarm, and the onboard veto.
9. **No certified secure element.** The STM32U585 has TrustZone, a hardware unique key and side-channel-resistant AES, but it's not a certified secure element. A skilled lab attacker could glitch it.
10. **An 8×13 LED matrix can't show everything.** Long or complex requests are refused. Safe, but limiting.
11. **Bugs beat maths.** This is new code written at a hackathon; that's far more likely to fail than ML-DSA. 41 tests help; the glue that talks to the board (Bridge arguments, LED matrix, Buttons, YubiKey assertion) is **not yet run on hardware**. An external review would help more.
12. **The supply chain** (how Binance was first breached): a poisoned library on the board or the laptop. Pinned dependencies and signed firmware reduce it.
13. **ML-DSA is young** (standardised 2024). That's why it's always paired with the YubiKey and the HMAC tag, and the root uses hash-based SLH-DSA.
14. **A compromised Linux side can tell the STM32 "calm".** With the second-opinion check dropped, the only guards are the onboard veto (extreme or missing sensor readings) and the duress PIN. A careful attacker who owns Linux and knows the design could suppress a model-only alarm.
15. **Mouse mode: no trusted display, so a swapped transaction is possible.** Malware on the laptop can show one request and send another, and the user's ordinary click approves it.
16. **Mouse mode: click piggybacking.** The STM32 sees *a* real click, not *which* click. Malware can wait for any ordinary click and arm its own request in the ~1.5 s window. It cannot act while the user is away from the mouse. Mitigations: narrow window, an arming rate limit, click-quality checks.
17. **Mouse mode: no deliberate duress signal.** The victim cannot say "I'm being forced". Detection is only passive (sensors, camera, the on-device model) and only at the moment of a transaction. A calm victim or a careful coercer can be missed, and bad days can raise false alarms.
18. **Mouse mode: no knowledge factor.** There is no PIN. The **owner check** (aggregated click, movement, grip and body features against the registered user's baseline) stands in for it. It is statistical: it can turn away the real owner and could be fooled by a close, informed impostor. Error rates are **unmeasured**. Handled by three bands (owner-like, uncertain to a step-up, not the owner to a quiet rejection), a learning-period mode and labels.
19. **Mouse mode: the YubiKey without a touch proves the key is plugged in, not that a person approved.** It is also **unverified** that our key allows it; if not, touch is used for step-up only.
20. **Mouse mode: a rooted UNO Q Linux side needs only a click to piggyback on.** It can't fake the sensor summary (the STM32 attests it, and the verifier recomputes the owner check), and it can't forge the tag, but it can try to get an approval started for a request the user didn't see.

## What we build when

| Wave | Crypto work | Code |
|---|---|---|
| **1. Skeleton** (now) | Run the existing tests. Provision a device. Flash the sketch. Run the verifier on the laptop. `enrol`, then one approval with a normal PIN and one with the duress PIN | `tools/provision.py`, `sketch.ino` + `yuseal_mcu.h`, `verifier.py`, `main.py` |
| **2. Real signals** | Real sensor window into the on-device model and the onboard veto; baselines; real nonce timing; persist the lockout counter if flash works; hash-chained log checks on the dashboard | `approve.py` (`model_fn`), `risk` rules for the veto, `sketch.ino` |
| **3. Response and polish** | YubiKey attestation at enrolment; org-root-signed certificates; YuDuino login with honeypot session; Merkle tree head on the dashboard | `yuseal.py`, a small root tool |
| **4. Harden and stretch** | Readout protection and a locked debug port; SLH-DSA root; check hybrid TLS is negotiated; Solana tree-head post; sealed mouse-shell screws | |

### After the hackathon

- **STM32 as the FIDO2 platform**, so Linux only relays encrypted CTAP2 traffic and never holds the hmac-secret.
- **ML-DSA on the STM32** (C library such as mldsa-native or PQClean; about 80 KB of RAM to sign, which fits in 786 KB), so the Linux side holds no signing key at all.
- **DHUK key wrapping, TrustZone (TF-M), secure boot** on the STM32U585.
- **A certified secure element** in the next hardware version.
- **Multi-person threshold signing**, so a big action needs a signature only 2 of 3 devices can make together.
- **A local model** (such as Gemma) on the Linux side, so no features leave the device.
- **Public witnesses** that co-sign the transparency log, and reproducible firmware builds.
- **A formal model** of the protocol in a tool like Tamarin or ProVerif, plus an external audit.
- **Post-quantum security keys** when they ship.

## Glossary

- **Signature:** proof that a specific private key approved specific bytes. Anyone with the public key can check it; nobody without the private key can make it.
- **Hash (SHA-256):** a fingerprint of data. Change one bit and the fingerprint changes completely.
- **HMAC:** a fingerprint that needs a secret key to make or check. The STM32's tag is one.
- **ML-DSA / SLH-DSA / ML-KEM:** NIST's post-quantum standards (2024): a lattice signature, a hash-based signature and a key-agreement method.
- **Hybrid:** using a classical and a post-quantum algorithm together, so you're safe if either holds.
- **Nonce:** a number used once, so an old message can't be replayed.
- **Forward secrecy:** stealing today's key doesn't unlock yesterday's messages.
- **Attestation:** a certificate built into the YubiKey at the factory that proves it's genuine.
- **Transparency log:** an append-only log anyone can check hasn't been rewritten.
- **Fail closed:** when in doubt, do the safe thing (here: hold and alert).
