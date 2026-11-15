# Marshall Wace: answering "New Worlds"

**Main audience (Jonah, 2026-11-14): Marshall Wace**, the hedge fund. Their DurHack challenge, from the opening ceremony slides:

> **New Worlds.** Make a project that explores the idea of New Worlds. Build something that opens a door to the unexplored, whether that's new data, ideas or something novel no one has seen before. Interpret the theme however you think best captures the spirit of this idea. They want to see **creativity, technical complexity and good presentation**.

Their other signals (from the same slides): they say technology and data are at the core of what they do, they invest in minimising **operational risk**, and they say they *don't* look for finance knowledge or a computer science degree. So **lead with the idea and the engineering, not with finance jargon.** (We don't copy their figures into this repo; see their slides.)

> **Not verified:** statements below about how a hedge fund works are general knowledge, not facts about Marshall Wace. Validate them with their team.

## The New Worlds pitch (Jonah's framing)

> The past few months have been the **worst ever for cyber security**, especially the Binance attack. In this **new AI-accelerated world** we need **peace of mind**. We are introducing a **future-proof, quantum-resistant** system that is **fully available to newer users**, who don't need to understand how it works, because there are **no inputs whatsoever**. In its base form it is an **unsuspecting connector** to the transfer application, **not explicitly listed**: the port just waits for "the key" and **doesn't say where it comes from**, which leaves a physical attacker very confused. It is built to be a **new kind of technology**.

How each line holds up, so we can say it without overclaiming:

| Line | What is true | Say it like this |
|---|---|---|
| **Worst months for cyber security, Binance** | Confirmed: 29 October 2026, about $6.3 to 6.4 billion, through a compromised laptop and an internal AI tool reaching the signing service ([PRIOR-ART.md](PRIOR-ART.md#facts-used-in-the-pitch-checked)) | "An attacker used an AI tool and a laptop to make Binance's own signer approve it. Nobody was asked." |
| **AI-accelerated world, peace of mind** | The Binance route went through an AI tool; AI also makes phishing and impersonation cheaper | "Approvals have to be something an AI-assisted attacker can't talk, click or script their way through" |
| **Future-proof, quantum-resistant** | The **approval signatures** are ML-DSA-65 (NIST FIPS 204), with an SLH-DSA offline root planned. The YubiKey part is still classical, which is why ML-DSA is required alongside it. We haven't had it reviewed | "Approvals are signed with a NIST post-quantum algorithm, so a future quantum computer can't forge them." Not "everything is quantum-proof" |
| **No inputs, fine for new users** | True for the **normal case** (a click you were going to make). Large or odd requests step up to a second approver | "Nothing to learn and nothing to do in the normal case" |
| **Encrypts in one of the most secure ways** | Mostly it **signs** rather than encrypts. The signing key is wrapped with AES-256 under a YubiKey secret; links use TLS | "The key can't be used without the YubiKey, the right hand and the click", not "it's encrypted in the most secure way" |
| **Unsuspecting connector, not listed** | Literally true on the computer: the device has **no USB connection to the laptop**, so it doesn't appear as a device or driver; only the ordinary mouse does. At the transfer application, a generic approval endpoint accepts a **valid signed envelope from an opaque signer ID** and says nothing about what produced it ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#misdirection-what-an-attacker-sees-in-the-logs)). **One hole:** the UNO Q joins Wi-Fi, so a client appears on the network with a name and MAC. Use a neutral hostname, a separate network, and don't claim it is invisible | "Nothing on the machine lists it, and the port doesn't say where its key comes from" |
| **Confuses a physical attacker** | Misdirection helps against someone who doesn't know the design; it fails against an insider or anyone who opens the mouse | Say it as an extra layer on the crypto, not the protection |
| **A completely new technology** | **Not defensible as worded.** Every part has prior art ([PRIOR-ART.md](PRIOR-ART.md)). We found no product or paper combining all of them | "**To our knowledge, a new combination** that none of the existing products or papers we found put together" |

**The defensible one-liner:** *In a world where AI helps attackers steal billions without breaking a single key, YuDuino gives approvals peace of mind: a post-quantum-signed, accountable approval that needs no input, no screen to trust and no training, hidden in a mouse nobody suspects.*

## How YuDuino opens three doors

| Door | What is new | Why it is unexplored |
|---|---|---|
| **New data** | A continuous, passive stream from **the human hand at the moment of authority**: grip, tremor, sweat, click style, movement style, in aggregate. Nobody collects this at the point where money moves or code ships | Market data and system logs are everywhere; **operator state** is almost never a risk input |
| **New idea** | **Authentication that is invisible**: no PIN, no screen, no extra action. The authenticator is a normal mouse and the check runs in the background | Security usually asks the person to do something; here the person does nothing and the **attacker doesn't know a check exists** |
| **Something novel** | A hand's **signature as a language**: meaningless readings composed into one signal that identifies the person and reads their state, and is even **audible** as music ([COMPOSITION.md](COMPOSITION.md)) | A new combination: mouse + YubiKey + post-quantum crypto + AI + a time-series database |

**One-sentence pitch for this brief:** *We opened a door to a new world of data: the human hand at the moment of authority, turned into an authenticator nobody can see, and a language nobody can read.*

**Technical complexity to point at (they asked for it):** an STM32 trusted core with a C++/Python equivalence test; three independent proofs including a post-quantum ML-DSA-65 seal; a hash-chained signed audit log; passive behavioural identification with a quiet-rejection design; a Tiger Data time-series pipeline (hypertable, continuous aggregates, compression, retention); Gemini as the duress judge.

**Good presentation to plan:** a working mouse handed to a judge, the dashboard that plays the session as music, a recorded backup, and the honest trade-offs said out loud.

## Overlaps worth using

These sponsors' challenges are close to ours. Recommended effort in [CHALLENGES.md](CHALLENGES.md#overlapping-sponsor-challenges); the short version:

- **SGX FX: "Protect your assets from a trading market storm"** (stay safe, early warning). Fits well: see below.
- **Neptune North: actors that stay resilient when comms fail.** Fits our fail-closed, independent-decision design; mention it, don't build for it.

## Tilt guard: operator state meets market state (an idea for SGX FX and this brief)

SGX FX asks for ways to **keep traders' money safe when things get rocky** and to **give an early warning**; they supply historical pricing data and say any data may be used. Combine their data with ours:

- From their pricing data, compute a simple **market regime** (for example rolling volatility) and mark "storm" periods.
- From the mouse, we have the **operator's state** (stress, fatigue, an unfamiliar hand).
- **Rule:** during a market storm, a large or limit-changing action from an operator whose state is off (stressed, or not the owner) goes to **step-up** (a second approver) and alerts the risk manager. Quiet markets and calm operators are untouched.
- **Demo:** replay a storm day from their data on the dashboard next to a live operator-state trace. When both spike, the guardian steps up.

**Caveats:** stress from the hand is noisy, so this is an *early warning to a human*, not a prediction or an automatic block. Monitoring staff has privacy and trust costs ([BASELINE.md](BASELINE.md#privacy)). Don't claim it predicts markets.

## Where a firm like this feels the pain

| Risk | Real-world shape | What YuDuino does |
|---|---|---|
| **Payment and treasury fraud** | A wire release, a margin transfer, or a **changed beneficiary or standing settlement instruction** approved on a spoofed screen or after a convincing email | Destinations are names from a **signed address book**; adding or changing one is a **danger action** that always needs a second approver. A swap is the weak spot in mouse mode, covered by limits and a cancel window ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)) |
| **Insider and rogue-trader risk** | One person overriding a limit, pushing a position or moving money, or **lending their credentials** to a colleague or assistant | Each approval is tied to a named person and, through the **owner check**, to *that person's hand*. A borrowed key or mouse in another hand is quietly rejected and alerts security |
| **Coercion** | A trader, treasury or ops person forced to approve, including physically (the "wrench attack" known from crypto) or by threat to family | Passive **duress detection** (sensors, camera, Gemini): the person sees a normal result, the outside sees "accepted", nothing moves, and the team is alerted silently |
| **Unsafe production changes** | A bad or malicious **algo or system deployment** reaching production (the 2012 Knight Capital loss is the usual cautionary tale) | `deploy`, `set_policy` and `add_signer` are **danger actions** that need two people, each with a signed, logged approval |
| **Risk-limit changes** | Quietly raising a limit before a trade | `set_policy` is a danger action. Add `limit_override` as another action type (small code change) |
| **Audit and accountability** | Regulators and internal audit ask **who authorised what, when, and could it have been forged?** | A **hash-chained, signed audit log**, with a Merkle tree head that can be published; every entry names the approver and device and verifies offline ([CRYPTO.md](CRYPTO.md#the-audit-trail-who-authorised-what)) |
| **Long-lived secrets** | Records and signatures that must hold for years | **ML-DSA-65** post-quantum signatures, and an SLH-DSA offline root, so today's approvals can't be forged later |

## What the mouse adds for an institution

- **Nothing on the desk looks like a security device.** It is a mouse. An attacker casing a trading floor looks for tokens and phones, not mice.
- **It authenticates continuously, with no friction.** Traders don't tolerate pop-ups and PINs; a click that "just works" fits how they actually work, and the owner check runs under the click ([OWNER-CHECK.md](OWNER-CHECK.md)).
- **Attribution that survives credential sharing.** Passwords, tokens and even hardware keys get shared on a busy desk; a hand can't be.

## Misdirection: even the logs mislead

Jonah's point: because the mouse is such an unusual place for an authenticator, **even an attacker reading the system logs and the transaction breakdown would assume the key is remote or that another ledger is in use**. Nothing in a normal log looks like "a person's hand on a mouse". The approval appears as an ordinary signature from a named signer, which suggests an HSM, an MPC service or a remote key. They go looking in the wrong place.

This is **security through misdirection on top of the crypto, not instead of it.** To keep it true, see [STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#misdirection-what-an-attacker-sees-in-the-logs).

## Likely objections, and honest answers

| They may ask | Honest answer |
|---|---|
| "A secret control is a problem for compliance." | Real tension. Keep it **secret from attackers but documented for auditors**: a controlled description for the compliance and audit owners, tested like any control. Don't make "nobody knows it exists" the only protection |
| "Behavioural biometrics is personal data." | It likely is: biometric data used to *identify* a person is special-category data under UK GDPR, and an employer using it needs a lawful basis and a **data protection impact assessment**. We keep **aggregates only**, with consent, pause, view and delete ([BASELINE.md](BASELINE.md#privacy)). **Get legal advice before any real deployment** |
| "What if it wrongly rejects my best trader at the wrong moment?" | The uncertain band goes to a **second approver**, not a lockout, with a service target. Time-critical actions can use a different tier. False rejects are unmeasured so far; we will show real numbers |
| "What if it fails closed during a market move?" | Fail-closed means a delay and a second approver, never a silent approval. The policy can set which actions may wait and which need a faster route. This must be agreed with the business |
| "No trusted screen?" | Correct, a deliberate trade-off for invisibility, listed openly. Caps, the address book, step-up, Gemini's check and a cancel window cover it. For large or irreversible actions use **strong mode** (PIN and screen) |
| "Is this certified?" | No. It's a hackathon prototype: no secure element, no certification, ML-DSA is new, and the code is not independently reviewed. The weak spots are listed in [CRYPTO.md](CRYPTO.md#remaining-weak-spots) |

## Suggested demo for this audience

1. **The treasury wire.** An ordinary click releases a small, in-policy wire with no extra input. Show the signed log entry naming the approver.
2. **The borrowed mouse.** A teammate uses the owner's mouse and gets an ordinary failure, every time. Show the one silent alert and the logged attempts.
3. **The coerced approval.** The owner clicks with a shaking hand and a second person in frame. The requester is told "accepted", nothing moves, and an alert and an incident report appear.
4. **The danger action.** Adding a new beneficiary needs a second approver, whatever the score.
5. **The audit view.** Tamper with one log line and show the chain fail.

Say the trade-offs out loud (no screen, no PIN, passive duress, statistical owner check). A firm like this values honesty about a control's limits more than a claim that it is perfect.

## Questions to ask at the stall

- Which approvals worry you most: payment release, beneficiary changes, limit overrides, deployments, or something else?
- Do you already use maker-checker (four eyes)? Where does it fail in practice?
- How do your traders and ops people feel about extra friction at the moment of action?
- Who must be able to understand and test a control like this: compliance, audit, information security?
- Is behavioural data from staff something you can use at all, and under what safeguards?

## Suggestions for the pitch

- Lead with the **Binance heist** (a signing service driven with no human approving) as the proof that approvals matter, then bring it to a **fund's treasury and deployment** risk.
- Make **accountability** the headline for this audience ("who authorised this, provably"), with **coercion and credential-sharing** as the memorable twist.
- Show **real numbers** from the owner check test ([OWNER-CHECK.md](OWNER-CHECK.md#how-we-will-find-out-if-it-works-hackathon-test)), not claims.
- Map each of their criteria (creativity, technical complexity, presentation) to a page here; see the table at the top.
