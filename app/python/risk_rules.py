"""Offline rules engine. Always runs, so the system still works if Gemini is slow or down.

Scores are deltas from the user's enrolled resting baseline, never absolute values:
skin, sweat and shaking differ a lot between people.
"""

def rules_score(features: dict, baseline: dict, face_count: int, pin_entry: str, user: dict) -> dict:
    signals = []
    score = 0.0

    # The explicit duress PIN is the strongest, most reliable signal.
    if pin_entry and pin_entry == user.get("duress_pin"):
        return {"score": 1.0, "signals": ["duress_pin_entered"], "explicit_duress": True}

    if face_count >= 2:
        score += 0.35
        signals.append(f"{face_count}_faces_in_frame")

    shake = features.get("shake_rms", 0) / max(baseline.get("shake_rms", 0.01), 0.01)
    if shake > 3:
        score += 0.25
        signals.append(f"shake_{shake:.1f}x_baseline")

    hum_delta = features.get("humidity", 0) - baseline.get("humidity", 0)
    if hum_delta > 8:  # % RH rise next to the palm
        score += 0.2
        signals.append(f"palm_humidity_+{hum_delta:.0f}%")

    moist_delta = features.get("moisture", 0) - baseline.get("moisture", 0)
    if moist_delta > 150:  # raw ADC counts; tune after wiring
        score += 0.1
        signals.append("moisture_up")

    if not features.get("touch"):
        signals.append("grip_released")

    return {"score": min(score, 1.0), "signals": signals, "explicit_duress": False}
