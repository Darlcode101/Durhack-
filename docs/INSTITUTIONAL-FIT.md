# YuDuino for an institutional trading firm (Marshall Wace and similar)

**Main audience (Jonah, 2026-11-14): Marshall Wace**, the hedge fund, alongside the tracks in [CHALLENGES.md](CHALLENGES.md). This page suggests how YuDuino fits a firm like that, what to say, what to demo, and what a firm like that would push back on.

> **Not in the repo yet:** Marshall Wace's own challenge brief and the pitch deck Jonah mentioned. Nothing below is taken from them. Once they are shared, check this page against them and change what doesn't match. Statements about how a hedge fund works are general knowledge, not facts about Marshall Wace; **validate them with their team on the day.**

## The one-line pitch

**An authorisation device that can't be phished, can't be forced without raising a silent alarm, can't be lent to someone else, and that an attacker doesn't even know is there.** Every approval names a person and is signed in a way a quantum computer can't forge.

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
- **Ask for the brief and the deck** and map each criterion to a page here.
