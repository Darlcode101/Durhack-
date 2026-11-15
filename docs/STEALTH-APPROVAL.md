# Invisible approval: no screen, no PIN, no extra input

**Design change (Jonah, 2026-11-14, evening).** The device is hidden in a mouse and must **work exactly like a normal mouse**. The user does **nothing extra**: no PIN, no rhythm, no gesture, no screen to read. They click "Process transaction" like any other button, and the authentication happens **in the background** from passive sensor data.

This page says how that works, what the crypto now looks like, and, just as important, **what protection this gives up**. Read the [what we lose](#what-we-lose-read-this) section before relying on it.

## The flow

```
 Laptop app             Customer's verifier         Mouse (UNO Q: STM32 + Linux)             Person
 ──────────             ────────────────            ────────────────────────────             ──────
 user clicks            ◄──── physical click on the mouse's left button, sensed by the STM32 ───┘
 "Process transaction"
        │ request
        ▼
   ┌─────────┐  nonce + digest of request  ┌──────────────────────────────────────────────────┐
   │ request │ ─────────────────────────►  │ 1 Linux arms the STM32 with the digest           │
   └─────────┘                             │ 2 STM32 checks: a real click in the last         │
                                           │   ~1.5 s, palm on the grip, not armed before     │
                                           │ 3 sensors already running (and the all-day       │
                                           │   baseline) give the features; camera frame      │
                                           │ 4 STM32 releases the unlock salt                 │
                                           │ 5 Linux unwraps the ML-DSA key (YubiKey in       │
                                           │   the dock, no touch)                            │
                                           │ 6 on-board model scores duress; STM32 decides   │
                                           │ 7 STM32 tags it, attesting the feature summary;  │
                                           │   Linux signs the envelope                       │
                                           └────────────────────────────────────────────────┬─┘
                                                                                              │ envelope
                          verifier checks ◄──────────────────────────────────────────────────┘
                          signatures, tag, owner check ─► "accepted" for normal and duress; a plain failure for an unknown hand
```

The person did one thing: the click they were going to make anyway.

**Does clicking "Process transaction" start the check? Yes, with one catch.** The *physical click* is the trigger, and the STM32 has to see it on the real button. The check itself (sensors, baseline, camera, the on-board model) is what runs "in the background", and it runs **only at the moment of a transaction**: everyday use is learned from but never judged for duress. The catch is that the STM32 cannot tell *which* click it was, only that a hand was clicking. That is the biggest new weak point (below).

## What the STM32 does now

Same small trusted core ([`yuseal_mcu.h`](../app/sketch/yuseal_mcu.h) today, changed later). It no longer has a PIN or a display, so it does this instead:

1. **Senses the physical button**, not the operating system. The mouse's switch contact is wired (read-only) to an STM32 pin, so malware on the laptop can fake an OS click but **cannot fake a switch closing**. Each click edge is stored with its time and whether the palm was on the grip.
2. **`arm(digest)`**: Linux gives it the approval's digest. The STM32 accepts only if there was a click with the grip held in the last **~1.5 seconds**, it isn't already armed, and it hasn't been armed too often this hour (a rate limit that replaces the PIN lockout).
3. **Releases the unlock salt** (`HMAC(K_REL, "unlock-salt")`), the same salt for every outcome, so Linux learns nothing about the result.
4. **`seal(score, veto)`**: as before, decides **N**, **S** or **D** from the model's number and the onboard veto, and returns the tag.

**The tag** is now `HMAC(K_TAG, "YS3/tag" | status | request digest | click_age_ms | grip | hash of the feature summary)`. It proves that *this STM32 saw a real click with the palm on the grip, this many milliseconds before this request*, what the status is, and **which sensor summary it was based on**. The envelope carries that summary (a dozen aggregate numbers) so the **verifier can recompute the owner check itself** ([OWNER-CHECK.md](OWNER-CHECK.md)). The verifier recomputes it for N, S and D and checks `click_age_ms` is small. As before, normal and duress tags look like the same 32 random bytes to anyone without the tag key.

## What changes in the crypto

| Part | v2 (in the code today) | Invisible approval (target) |
|---|---|---|
| Presence proof | PIN on the buttons, display text shown | **Physical click with palm on grip**, sensed on the STM32 |
| What the STM32 tag covers | status, hash of the text on the matrix, digest | status, digest, **click age**, grip |
| Key release | salt after the correct PIN | salt after **arm with a recent click and palm** |
| YubiKey | signature over the digest, **touch required** | signature or hmac-secret **without a touch** (see below) |
| Duress signal | duress PIN **or** a cloud model | **The on-device Edge Impulse model and the onboard veto only, judged only at the moment of a transaction** |
| Who is it? | the PIN, plus a YubiKey touch | **The owner check**: the verifier compares the STM32-attested click, movement, grip and body features with the registered user's baseline, and quietly rejects other hands ([OWNER-CHECK.md](OWNER-CHECK.md)) |
| Lockout | 5 wrong PINs | **Rate limit on arming** |
| Request display | LED matrix, trusted | **None** |
| ML-DSA seal, audit log, hash chain, nonces, verifier checks | as before | **unchanged** |

**The YubiKey is the open question.** A touch is an input, so "no input of any kind" means **no touch**. The plan: leave the YubiKey plugged into the dock and ask it for the hmac-secret and an assertion **without user presence** (CTAP2 has an `up` option; **unverified on our key, test it**). That proves the key is *there*, not that a human touched it. If the key refuses to work without a touch, fall back to touch **only for step-up** (below), and let the mouse's click be the ordinary-case human proof.

**The owner check (a headline feature).** The all-day baseline ([BASELINE.md](BASELINE.md)) lets the verifier tell whether the hand on the mouse is **the YubiKey's registered user**, from how they move, grip and click and from their body's baseline, all combined. This is the **"something you are"** factor and it replaces the PIN's "something you know". Another person gets a plain, ordinary-looking failure and can retry forever without ever passing; nothing tells them why. Full design, false-reject handling and the test plan: **[OWNER-CHECK.md](OWNER-CHECK.md)**. **It is statistical, not proof**, so it is one layer: it can reject, or push to step-up, and a pass is never enough alone.

## Tiers: invisible by default, a step up when it matters

| Situation | What the user does | Why |
|---|---|---|
| Normal request, owner-like hand, calm | **Nothing extra** | The whole point |
| Hand is **uncertain** (not quite the owner, or little data for this hour) | **A step-up result** for the customer's system to handle | A real owner having an odd day is slowed, not locked out |
| Hand is **clearly not the owner** | Nothing; the requester sees an ordinary failure | The impostor can retry forever and never pass; repeats lock the member |
| Duress score high, or the model or the sensors can't give a verdict | **Verdict `duress`**; the requester is told "accepted" | Fail closed, quietly |

## Misdirection: what an attacker sees in the logs

Jonah's point: the mouse is such an unusual place to put an authenticator that **even in the system logs and the breakdown of a transaction, an attacker would assume the key is remote or that another ledger is being used.** An approval looks like an ordinary signature from a named signer, which suggests an HSM, an MPC service or a remote key. They go looking in the wrong place. This is misdirection **on top of** the crypto, never instead of it.

To keep it true:

- **Opaque signer names.** Anything outside the verifier's security boundary (dashboards, exports, ledger entries) shows a generic signer ID, not "mouse", "unoq-1", "grip" or anything else about the device.
- **Keep sensor and click fields inside.** The click age, the feature hash and the sensor summary stay in the verifier's internal record. External logs carry the signature, the signer ID, the request and the time only.
- **Uniform behaviour.** Decoys and ordinary failures use the same fields and timing as real ones ([OWNER-CHECK.md](OWNER-CHECK.md)).
- **Mind the timing.** An approval arrives about a second after a human click. Don't expose enough timing detail in outside logs to show the pattern.
- **The signature is unusual.** An ML-DSA-65 signature is large (about 3.3 KB) and stands out on a ledger. It looks like "a post-quantum remote signer", which is the intended guess, but a careful analyst could ask why. Don't rely on it.

**Limits.** Anyone who has seen the mouse, or an insider who knows, defeats this. **It must never be the only protection.** And an institution's auditors and regulators need to understand the control, so it should be **secret from attackers but documented for authorised auditors** ([INSTITUTIONAL-FIT.md](INSTITUTIONAL-FIT.md#likely-objections-and-honest-answers)).

## What we lose (read this)

This is not as strong as v2. In plain words:

1. **No trusted display, so no protection against a swapped transaction.** In v2 the LED matrix showed exactly what was signed on a screen the laptop didn't control, so malware could not change "pay 10 to Alice" into "pay 10,000 to Mallory" without the person seeing. **Now the only screen is the laptop's.** Malware on the laptop can show Alice and send Mallory, and the user's normal click approves it. *This breaks Jonah's earlier hard rule* (2026-11-11) that the device screen shows exactly what is being approved.
2. **The trigger can't tell which click it was.** The STM32 sees a real click, not "the click on Process transaction". Malware can **wait for any ordinary click** (the user clicks all day) and arm a request of its own within the ~1.5 s window. It can't act while the user is away from the mouse, but it can ride their clicks.
3. **No deliberate duress signal.** The victim cannot say "I'm being forced". Detection is purely passive and happens only at the moment of a transaction: the on-device model reading the sensors. A calm or well-trained victim, a coercer who is careful, or an ordinary bad day on the sensors can all go the wrong way. Errors cut both ways: missed duress and false alarms.
4. **No PIN, so no knowledge factor.** Anyone who can grip the mouse and click while the YubiKey is in the dock can *start* an approval. The **owner check** is what stands in for the PIN, and it is statistical: it can wrongly reject the real owner and can wrongly accept a determined, informed impostor. We haven't measured its error rates.
5. **YubiKey without a touch** proves the key is plugged in, not that a person approved.
6. **A compromised UNO Q Linux side is more dangerous.** In v2 a rooted Linux still needed the PIN and the displayed text. Now it only needs a click to piggyback on.

## Best mitigations (what we actually rely on)

Because the device can no longer vouch for *what* is being approved, the weight moves to the **verifier** and to the **on-device model**:

| Mitigation | What it covers |
|---|---|
| **Click quality.** The STM32 only counts a click with a natural button-press impulse on the accelerometer and the palm on the grip | Cheap injected signals |
| **Narrow window (~1.5 s) and an arming rate limit** | Slows piggybacking |
| **Owner-likelihood and duress from the baseline** | A thief, or a stressed owner, gets a step-up or a hold |
| **Everything still fails closed, and the audit log is unchanged** | Missing or odd data means hold, and every decision is traceable |

## Weak spots this adds

These are also in [CRYPTO.md](CRYPTO.md#remaining-weak-spots):

- **A:** swapped transaction, no trusted display.
- **B:** click piggybacking (the STM32 can't tell which click).
- **C:** no deliberate duress signal; purely passive detection, only at the moment of a transaction.
- **D:** no knowledge factor; the owner check is only statistical (false rejects and false accepts, unmeasured so far).
- **E:** YubiKey without touch is possession only (and **unverified** that our key allows it).
- **F:** a rooted UNO Q Linux side now needs only a click to piggyback on.

## The code

This is built (2026-11-15), tested on a laptop and **not yet run on the board**:

- **`yuseal_mcu.h`:** click edges (time and grip), `arm(digest)` with the 1.5 s rule and a rate limit, `attest()`, and the new tag. No PIN, no display.
- **`yuseal.py`:** the new tag, a `SoftMcu` twin, the click-age check, the owner check (`Baseline`, three bands), the quiet failure, repeat lock and alerts.
- **`approve.py`, and the reference `Verifier` in `yuseal.py`:** arm on the click, no PIN wait, one uniform public failure.
- **`sketch.ino`:** reads the switch line (read-only) and computes the ten features at arm time.
- **Tests:** swap, replay, forged-tag, wrong-key, piggyback and click-age tests, plus the owner check.
- **Not built:** the all-day baseline storage in the verifier.
- **Hardware:** a donor mouse with a read-only tap on its left-button switch.

## For the hackathon

- **Demo the invisible path:** click, and the approval goes through with no extra input. Then demo duress: the same click with the hand shaking (or a second face in the camera) is accepted on the outside and reads `duress` to the verifier.
- **Be honest on stage about the trade-off:** say that this version gives up the trusted screen and the PIN for invisibility. That is a strength in the pitch, not a weakness.
