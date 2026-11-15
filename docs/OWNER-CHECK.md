# The owner check: the mouse knows whose hand it is

**The idea (Jonah, 2026-11-14):** the mouse should **reject anyone who is not the person the YubiKey is registered to**, without anyone asking for a password or a gesture. It does this from how the person **moves, grips and clicks, and from their body's baseline**, all combined. Because nobody knows the mouse is an authenticator, an impostor can **try for as long as they like and never get a pass**, and each try just looks like an ordinary failure.

This is the replacement for the PIN's "something you know": it is **something you are**, measured quietly all day ([BASELINE.md](BASELINE.md)). It is also the clearest version of the project's idea: **a language the attacker can never read.** Nothing is secret to steal. The "password" is the whole shape of a person's hand at work, which nobody knows exists, and which no one signal gives away.

> **Honest limit up front.** Behavioural identification is *statistical*. It will wrongly reject the real owner sometimes and wrongly accept a determined impostor sometimes. We have **not measured our error rates** and must not claim any. The design below limits the damage of both kinds of error. It is one layer, never the only one.

## What the mouse measures

All of these are computed **on the STM32 as aggregates** (a mean and a spread over a window). No raw movement, no cursor positions, no keystrokes ever leave it.

| Group | Features | Sensor |
|---|---|---|
| **Click behaviour** | how long a click is held, the gap between a double-click, how hard the click shakes the shell, the pause between "arrive" and "click" | the mouse's switch lines (read-only tap) and the accelerometer |
| **Movement style** | speed profile, smoothness (jerk), how long the hand rests between moves, how big the typical sweep is | accelerometer and gyro (Modulino Movement); the mouse's own optical sensor stays with the laptop |
| **Grip** | how much of the palm is on the pad, the contact resistance of the palm pads (a proxy for hand size and where it rests), time with the palm down | touch sensor, moisture pads |
| **Body** | tremor power and **peak frequency** (a personal trait), palm humidity and how it changes, temperature range | Movement, Thermo, moisture pads |
| **Scroll behaviour** (optional) | wheel tick rate and bursts | wheel line, if tapped |

The *combination* is the point. Any one of these can be copied or is shared by many people. Matching **all of them at once**, for the right hour of the day, without knowing what is being measured, is much harder.

## How the decision is made

1. **Per-user, per-hour baseline** for every feature (median and spread), built from the person's own all-day use ([BASELINE.md](BASELINE.md), stored in Tiger Data).
2. **Recent window:** the last few minutes of quiet-hand features plus the moment of the click.
3. **Distance from the owner:** for each feature, how far the window is from the person's usual (robust z-score, each capped so one odd feature can't dominate), then a weighted combination into one number. This is plain, explainable statistics for the hackathon. A learned model (for example one-class) can replace it later.
4. **Continuity:** the verifier also tracks whether the hand has been **continuously the same**. If the palm leaves the pad for more than a few seconds, a new hand may have picked it up, and **trust restarts from low** and has to be earned again over a minute or more of matching quiet data. Someone grabbing the mouse and immediately clicking gets no benefit of the doubt.
5. **Three bands, not one cut-off:**

| Band | Meaning | Outcome |
|---|---|---|
| **Owner-like** | Close to the person's usual for this hour, with continuity | Carry on to the normal checks |
| **Uncertain** | In between, or not enough history yet for this hour | **Step-up**: returned to the customer's system to handle |
| **Not the owner** | Clearly different, or continuity broken | **Rejected quietly** (below) |

**Where it runs.** The STM32 **attests** the features: the tag covers a hash of the feature summary and the envelope carries the summary (a dozen numbers). The **verifier recomputes** the distance from those attested numbers and the Tiger Data baseline itself. So **a compromised Linux side cannot claim "it's the owner"**, and it cannot replay a recording of the owner's data without physically feeding the sensors. (Gemini's duress score still travels through Linux, as before.)

## How a rejection looks to an impostor

The impostor must never learn *why* it failed, and must never see anything that tells them they are getting closer.

- **Unknown hand:** a plain, ordinary-looking failure ("temporarily unavailable, try again"). Same text, same delay as any other transient failure. **Not** "wrong person".
- **Duress:** still the decoy: the requester is told "accepted" and nothing executes, as in [CRYPTO.md](CRYPTO.md). The two cases are handled differently on purpose: a coerced person's attacker should believe it worked, while an impostor should keep retrying in vain.
- **No score, no hint, no timing difference** is returned on any path. (If the outcome leaked how close the attempt was, an attacker could hill-climb toward the owner's profile.)
- **After several unknown-hand rejections in a few minutes**, the verifier locks that person's approvals and records an alert for the customer's system to read. The attacker keeps seeing the same ordinary failures.
- Each rejected attempt is **logged** with the attested features, so there is evidence of who tried and when.

## The false-reject problem (the real owner turned away)

It will happen. Hands change: cold or sweaty, an injury, a glove, a new chair, a bad night, a stressful hour. Stress also looks like duress, so these can pile up. What we do:

1. **The uncertain band is a step-up, not a rejection.** Most "not quite right" cases land on a step-up result, so the owner is slowed down, not locked out.
2. **A learning period.** Until there are enough hours of data for a given hour of day, the owner check is **advisory only**: it records and flags but doesn't reject. This stops a first-day lockout, which matters for the hackathon.
3. **Labels teach it.** When the owner says "that was me", the window is labelled and added to the baseline (and tunes the thresholds in Tiger Data). Over time, false rejects fall.
4. **A recovery path.** If a real owner is rejected, the customer's system decides how they re-verify; repeated rejections of the owner trigger a human review rather than a silent lockout.
5. **Thresholds are set conservatively and measured.** See the test below.

## What it does *not* do

- It is **not a strong secret.** A close, informed, determined impostor (someone who studies the owner and knows what is measured) might get through. It raises the cost of casual and unknowing attackers a lot, and the rest of the stack (step-up, YubiKey, audit log) still applies.
- It does **not** replace the YubiKey. The credential is still the owner's; the owner check just says whether the hand using it matches.
- It cannot protect against the owner being **coerced** (the right hand under duress); that is the duress score's job, and it has no deliberate signal ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)).
- **Privacy:** it needs aggregated behavioural data about a person. Consent, pause, view and delete controls apply ([BASELINE.md](BASELINE.md#privacy)).

## How we will find out if it works (hackathon test)

Do this before putting any weight on it. It is quick and gives real numbers.

1. Two or three people each use the same mouse normally for an hour or more, after the owner's baseline exists.
2. Replay each person's windows through the distance score against the **owner's** baseline.
3. Plot how well the owner's windows separate from the others'. Pick thresholds; count wrong accepts and wrong rejects.
4. Report the **real** numbers and sample sizes on the dashboard and in the pitch, including if it separates poorly. If it does, say so and keep the owner check *advisory*.

## Build order

| Step | What | Test |
|---|---|---|
| 1 | STM32 computes the per-minute click, movement, grip and body features; MAC-attests them | A tampered feature fails the tag check |
| 2 | Verifier stores them in Tiger Data and builds per-hour baselines | The dashboard shows an hourly profile |
| 3 | Verifier computes the distance, the three bands and continuity | A second person gets "uncertain" or "not the owner"; the owner gets "owner-like" |
| 4 | Quiet rejection, lock after repeats, and the alert | Repeated tries give identical failures and a recorded alert |
| 5 | Learning-period mode, labels and the recovery path | A new user is never rejected on day one |
