"""How the body sensors are judged against the user's own normal. Pure and deterministic:
the same readings and baselines always give the same result, so any past verdict can be
recomputed exactly from what the local store holds.

Two baselines, both from the local store:
  usual   this user's normal for this HOUR OF DAY: 14 days of hand-on-mouse readings from
          everyday use, gaming and busy days included (hourly aggregates). Falls back
          to the 30 s session calibration.
  recent  the user's own LAST 20 MINUTES of hand-on-mouse readings. Everyday use always counts;
          readings from a transaction count only if it was judged normal, so a flagged approval
          can't teach the model that pressure is normal.

Nothing is ever raised outside a transaction: everyday readings are learned from, never judged.

The idea: a run, a sleepless night or a lot of coffee shift your WHOLE state gradually, so
they show against "usual" but not against "recent". Coercion is a SUDDEN change at the moment
of approval, so it shows against "recent". Rules (per signal):
  * state shift (recent window itself well above usual): judge mainly against recent; only an
    extreme deviation from usual still counts (partly), and goes to the camera tie-breaker.
  * just back after an absence, too early for a recent window: judge against usual, but if the
    signal is elevated and easing off (or it's too early to tell), treat it as recovery from
    exertion: the body sensors alone may not declare duress; the camera decides.
  * otherwise: judge against both.
Learning from corrections: each incident labelled "false alarm" at this time of day widens the
tolerance by 10%, capped at 1.5x. Bounded and logged, so it can't be trained away.

Why not reinforcement learning: real coercion is too rare to give a reward signal, a learning
policy isn't reproducible for audit, and an attacker could train it with repeated calm-looking
pressured approvals.
"""
import math

KEYS = {"humidity": 0.5, "moisture": 5.0, "shake_rms": 0.01}   # key -> minimum standard deviation
GROUPS = {"sweat": ("humidity", "moisture"), "movement": ("shake_rms",)}

MIN_USUAL_N = 600          # >= 10 minutes of calm readings at this hour across the last 14 days
RECENT_WINDOW_S = 20 * 60  # recent baseline: the last 20 minutes...
RECENT_SKIP_S = 2 * 60     # ...excluding the last 2, so the current moment isn't its own baseline
MIN_RECENT_N = 120         # >= 2 minutes of calm readings in the window
ABSENCE_S = 5 * 60         # a gap this long in hand-on-mouse readings = the user was away
RETURN_WINDOW_S = 15 * 60  # "just back" for this long after an absence
SHIFT_SIGMA = 1.5          # recent window this far above usual = a state shift
EXTREME_OFFSET = 2.5       # under a state shift, deviation from usual beyond this still counts
RECOVERY_CAP = 0.6         # body score cap while recovering: stays in the camera's band (< 0.75)
FALSE_ALARM_STEP, MAX_TOLERANCE = 0.10, 1.5


def z_to_score(z):
    """0 at 1.5 sigma above normal, 1 at 4.5 sigma. Below normal never counts."""
    return None if z is None else max(0.0, min(1.0, (z - 1.5) / 3.0))


def combine(scores):
    s = [x for x in scores if x is not None]
    if not s:
        return None
    hi, lo = max(s), min(s)
    return min(1.0, hi + 0.5 * lo) if len(s) > 1 else hi


def pool(parts):
    """Pooled mean and standard deviation from per-hour (mean, sd, n) rows."""
    parts = [(m, sd or 0.0, n) for m, sd, n in parts if m is not None and n]
    total = sum(n for _, _, n in parts)
    if not total:
        return None
    mean = sum(m * n for m, _, n in parts) / total
    ss = sum((n - 1) * sd * sd + n * (m - mean) ** 2 for m, sd, n in parts)
    return mean, math.sqrt(ss / max(total - 1, 1)), total


def _stats(values):
    v = [x for x in values if x is not None]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)), len(v)


def _slope_per_min(points):
    """Least-squares slope (units per minute) of (t, value) points."""
    pts = [(t, v) for t, v in points if v is not None]
    if len(pts) < 10:
        return None
    mt = sum(t for t, _ in pts) / len(pts)
    mv = sum(v for _, v in pts) / len(pts)
    den = sum((t - mt) ** 2 for t, _ in pts)
    return None if den == 0 else 60.0 * sum((t - mt) * (v - mv) for t, v in pts) / den


def recent_from_rows(rows, now):
    """rows: [(t, humidity, moisture, shake_rms, verdict)] of hand-on-mouse readings, last 30 min,
    in time order. Returns the recent baseline, when the user came back, and recent trends."""
    # Treat the start of the 30-minute query as the last time the hand was seen: a gap of
    # ABSENCE_S or more (including at the very start) means the user was away and came back.
    returned_at = None
    prev = now - 30 * 60
    for r in rows:
        if r[0] - prev >= ABSENCE_S:
            returned_at = r[0]
        prev = r[0]
    start = max(now - RECENT_WINDOW_S - RECENT_SKIP_S, returned_at or 0)
    # Everyday (background) use always counts, gaming included: it IS this person's recent state.
    # Readings taken during a transaction only count if that transaction was judged normal.
    usable = lambda r: (len(r) > 5 and r[5] != "approval") or r[4] == "NORMAL"
    window = [r for r in rows if start <= r[0] < now - RECENT_SKIP_S and usable(r)]
    since = [r for r in rows if r[0] >= (returned_at or now - 10 * 60) and r[0] >= now - 10 * 60]
    idx = {"humidity": 1, "moisture": 2, "shake_rms": 3}
    return {
        "stats": {k: _stats([r[i] for r in window]) for k, i in idx.items()},
        "n": len(window),
        "returned_s": None if returned_at is None else now - returned_at,
        "slope": {k: _slope_per_min([(r[0], r[i]) for r in since]) for k, i in idx.items()},
    }


def tolerance_for(false_alarms: int) -> float:
    return min(MAX_TOLERANCE, 1.0 + FALSE_ALARM_STEP * max(0, false_alarms))


def _z(x, ref, key, tol):
    if x is None or not ref or ref.get(key) is None:
        return None
    m, sd = ref[key][0], ref[key][1]
    return (x - m) / max(sd or 0.0, KEYS[key]) / tol


def assess(now_vals: dict, usual: dict | None, recent: dict | None, session: dict | None,
           tolerance: float = 1.0) -> dict:
    """now_vals: current smoothed readings. usual: {key: (mean, sd, n)} for this hour (or None).
    recent: output of recent_from_rows (or None). session: {key: (mean, sd)} 30 s calibration."""
    usual_ok = usual and sum((usual.get(k) or (0, 0, 0))[2] for k in KEYS) >= MIN_USUAL_N
    ref_usual = usual if usual_ok else session
    kind = "usual for this hour" if usual_ok else ("this session" if session else None)
    returned_s = recent["returned_s"] if recent else None
    just_back = returned_s is not None and returned_s < RETURN_WINDOW_S
    recent_ok = bool(recent) and recent["n"] >= MIN_RECENT_N
    if recent_ok and kind:
        kind += " + last 20 min"

    out = {"baseline_kind": kind, "tolerance": round(tolerance, 2), "returned_s": returned_s,
           "groups": {}, "explanations": []}
    group_scores, recovering = {}, False
    for g, keys in GROUPS.items():
        best = None   # the most concerning key in the group
        for k in keys:
            zu = _z(now_vals.get(k), ref_usual, k, tolerance)
            zr = _z(now_vals.get(k), recent["stats"], k, tolerance) if recent_ok else None
            shift = None
            if recent_ok and ref_usual and ref_usual.get(k) and recent["stats"].get(k):
                shift = (recent["stats"][k][0] - ref_usual[k][0]) / max(ref_usual[k][1] or 0.0, KEYS[k]) / tolerance
            state = "normal"
            if zr is not None and shift is not None and shift >= SHIFT_SIGMA:
                eff = max(zr, (zu or 0) - EXTREME_OFFSET)
                state = "shift"
            elif zr is not None:
                eff = max(z for z in (zr, zu) if z is not None)
            else:
                eff = zu
                slope = (recent or {}).get("slope", {}).get(k)
                if just_back and zu is not None and zu >= 2 and (slope is None or slope <= 0):
                    state = "recovering"
            cand = {"key": k, "z_usual": None if zu is None else round(zu, 2),
                    "z_recent": None if zr is None else round(zr, 2),
                    "shift": None if shift is None else round(shift, 2), "z": None if eff is None else round(eff, 2),
                    "state": state}
            if best is None or (eff or -99) > (best["z"] or -99):
                best = cand
        out["groups"][g] = best
        group_scores[g] = z_to_score(best["z"]) if best else None
        if best and best["state"] == "recovering":
            recovering = True

    body = combine(group_scores.values())
    if body is not None and recovering:
        body = min(body, RECOVERY_CAP)
    out["body"] = body

    sweat, move = out["groups"].get("sweat"), out["groups"].get("movement")
    if any(gr and gr["state"] == "recovering" for gr in (sweat, move)):
        out["explanations"].append("you're just back and your readings are easing off, like after exercise, "
                                   "so the body sensors alone won't raise an alarm")
    for name, gr in (("sweat", sweat), ("movement", move)):
        if gr and gr["state"] == "shift":
            out["explanations"].append(f"your {name} has been higher than usual for a while (tiredness, coffee or "
                                       f"exercise), so it's judged against your last 20 minutes")
    if tolerance > 1.0:
        out["explanations"].append(f"tolerance widened to {tolerance:.1f}× after false alarms at this time of day")
    return out
