# The all-day baseline

**The idea (Jonah, 2026-11-14):** a mouse is held for hours every day. So the device can quietly learn what *this person's* hand normally feels like, instead of relying on a single one-minute enrolment. That fixes the hardest problem in duress detection: not having enough data to say what "irregular" means.

The mouse therefore does two jobs: it **hides the device**, and it **feeds the baseline**. The baseline is only learned from all day: **duress is judged only at the moment of a transaction**, never from everyday use. See [MOUSE-DESIGN.md](MOUSE-DESIGN.md) for the hardware and [CHALLENGES.md](CHALLENGES.md#4-mlh-best-use-of-tiger-data) for how Tiger Data fits.

## What this changes

| Before | Now |
|---|---|
| One minute of calm readings at enrolment | A **continuously updated** baseline from normal use, plus a short enrolment to start |
| One handheld grip that you pick up for an approval | A mouse that is **already in your hand**, so a duress reading is compared with hundreds of normal hours |
| Hard to say what "your usual tremor" is | Per-person ranges, by time of day, built from thousands of samples |

**Gemini's job is unchanged.** It still calculates the duress verdict and fails closed. It just gets better inputs: each feature as a deviation from *this person's* usual value for this hour.

> **This baseline now also powers the owner check** ([OWNER-CHECK.md](OWNER-CHECK.md)): the same features, plus click, movement and grip features, are compared with the registered user's usual to reject other hands. The feature list below is the minimum; the owner check adds the click and movement groups.

## What the mouse measures all day

Every minute (while the hand is on the mouse), the STM32 computes **one row of aggregate features**. Never raw data.

| Feature | From | Notes |
|---|---|---|
| `grip_fraction` | touch sensor | share of the minute the palm was on the pad |
| `tremor_4_12hz` | Movement | band power, only from **quiet** windows (see below) |
| `humidity`, `humidity_delta` | Thermo | humidity under the palm, and the change over the last few minutes |
| `temp` | Thermo | drifts with the board's heat and the room, so it is used relative to the person's own range |
| `moisture` | moisture pads | contact and sweat proxy, relative to the person's own range |
| `still_fraction` | Movement | how much of the minute the mouse was resting rather than moving |
| `n_samples` | counter | how many quiet samples the row is based on (for trust) |

That is about 1,440 small rows per person per day at most: tiny for Tiger Data.

## Filtering out normal mouse movement

Using a mouse is not tremor. A sample only counts toward the tremor feature when **all** of these hold:

1. **Grip held** (touch = 1): the palm is on the mouse.
2. **Mouse still:** low-frequency movement is small, so the hand is resting rather than sweeping the cursor. Large, slow motion means "the mouse is being moved" and is dropped.
3. **Away from clicks:** ignore 100 ms either side of a key press, so a click isn't read as a shake.
4. **Band-pass filtered to 4 to 12 Hz** (physiological tremor), after removing the average (gravity).

Each row is also **tagged** with `still_fraction`, so quiet and busy minutes are never mixed in one average. The approval itself happens on a still mouse, so it is compared with the **quiet-hand** baseline.

## Time of day and drift

The baseline moves: hands are different at 9 am and at 11 pm, after coffee, after exercise, on a hot day. So:

- **Bucket by hour of day** (and weekday versus weekend once there is enough data). Tiger Data keeps these as **continuous aggregates** over a time-series hypertable, so one fast `time_bucket` query returns "your usual tremor at this hour". The table design and SQL are in [CHALLENGES.md](CHALLENGES.md#4-mlh-best-use-of-tiger-data).
- **Robust statistics:** medians and spread, not plain averages, so a stressful afternoon doesn't skew the baseline. The plain SQL sketch uses average and standard deviation; switch to approximate percentiles if the Tiger Data hyperfunctions are available.
- **Not enough data in a bucket?** Fall back to the next wider bucket (the whole day), then to the **population prior**. A bucket needs a minimum number of quiet samples before it is trusted.
- **Slow drift:** a weighted recent average over the last few weeks, so the baseline follows the person as they change.
- **Within-session check:** readings from the first seconds of the approval are compared with the last ones, so a sudden change mid-approval stands out even if the long-term baseline is wide.
- **Ambient effects:** the Thermo sits in the mouse next to a warm board, so absolute temperature is weak. Humidity change and the person's own ranges are the useful signals.

## Privacy

- **Only aggregate features leave the STM32.** No raw acceleration, no cursor movement, no clicks, no keystrokes and nothing about *what* the person is doing on the computer. The mouse has no idea what the screen shows.
- **No camera frames or audio in the baseline.** Those are used only during an approval, as now, and not stored.
- **Per-user and consented.** Each team member agrees to it; the person can **see their own data, pause collection and delete it**. Reading emotion at work is restricted in some places (for example the EU), so the framing stays *context risk scoring for consenting people*.
- **Retention:** minute rows for about 30 days, then only the hourly aggregates (kept for months). Compression keeps it small.
- **A visible indicator.** The device never collects while a "pause" is set, and the pause state is shown on the matrix when the mouse is picked up.

## Keeping the baseline honest (poisoning)

If someone else uses the mouse for days, they would teach it *their* hands. So:

- Samples count toward the baseline only when the **owner check passes with continuity** (the same hand, held continuously) or after an approval the guardian accepted as normal. Other samples are kept in a separate "unverified" bucket and are not used. (There is no PIN any more to prove the owner is present.)
- **Samples from a duress approval are never added**, and neither is the hour around one.
- A person who is being coerced for a long time is a limit we can't remove; there is no deliberate duress signal in mouse mode, so this is a limit we state openly ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md)).

## Where each part runs

| Piece | Where | Wave |
|---|---|---|
| Quiet-window filter, band-pass, per-minute features | STM32 (`sketch.ino`) | 2 |
| Minute rows collected and posted | Linux (`main.py` background logger) to the guardian over HTTPS | 2 |
| Hypertable, hourly continuous aggregates, retention, compression | Tiger Data | 2 |
| Baseline lookup (hour bucket, fallbacks, prior) | Guardian, passed to Gemini with the verdict request | 2 to 3 |
| Pause, view and delete my data | Guardian endpoint and dashboard | 3 |

## For the hackathon

There is no all-day data yet. So:

- **Use the mouse as your own mouse from now until the demo** (see the "needs to be a real mouse" note in [MOUSE-DESIGN.md](MOUSE-DESIGN.md)). Even a few hours of real use gives a real baseline to show.
- Start with the **one-minute enrolment and the population prior**, then switch to the hourly buckets as rows arrive. The dashboard shows the baseline filling in over the day, which is a good demo for the Tiger Data prize.
- Do not invent numbers. Show real rows, and say how many hours they cover.
