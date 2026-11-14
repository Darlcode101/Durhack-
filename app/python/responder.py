"""Respond: decide the outcome and act on it.

normal    -> grant
uncertain -> step-up (ask for another factor / retry)
duress    -> decoy grant (looks normal to the attacker) + silent alert + audit log
"""
import json
import os
import time

import requests

AUDIT_LOG = os.path.join(os.path.dirname(__file__), "audit.log")  # no images, just decisions

STEP_UP_AT = 0.4
DURESS_AT = 0.7


def decide(rules: dict, gemini: dict | None) -> dict:
    # Gemini can only raise risk: take the max, never let it lower the rules score.
    g = gemini["duress_score"] if gemini else 0.0
    score = max(rules["score"], g)
    if rules.get("explicit_duress") or score >= DURESS_AT:
        outcome = "duress"
    elif score >= STEP_UP_AT:
        outcome = "step_up"
    else:
        outcome = "grant"
    return {
        "outcome": outcome,
        "score": round(score, 2),
        "rule_signals": rules["signals"],
        "gemini": gemini,
    }


def act(user: str, decision: dict) -> str:
    """Returns what the UI should show. Duress shows the SAME screen as grant."""
    entry = {"t": time.time(), "user": user, **decision}
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    if decision["outcome"] == "duress":
        _silent_alert(user, decision)
        return "grant"  # decoy: attacker sees a normal success
    return decision["outcome"]


def _silent_alert(user: str, decision: dict):
    url = os.environ.get("ALERT_WEBHOOK_URL")
    if not url:
        print("[alert] no ALERT_WEBHOOK_URL set; duress logged only")
        return
    try:
        msg = f"⚠️ Possible duress login for {user} (score {decision['score']}): {', '.join(decision['rule_signals'])}"
        requests.post(url, json={"content": msg}, timeout=3)  # Discord webhook format
    except Exception as e:
        print(f"[alert] failed: {e}")
