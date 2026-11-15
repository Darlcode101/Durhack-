"""The guardian: the only route to "execute". Run on Vultr (or on the laptop for Wave 1).

    uvicorn guardian:app --host 0.0.0.0 --port 8000      (put HTTPS in front on Vultr)

Holds only PUBLIC keys and the tag key for each device, so if it is hacked it can refuse
or leak alarms but can't make an approval. Wave 1 keeps its state in memory (a restart means
re-enrolling); Wave 3 persists it.

    POST /nonce                       -> {"nonce": ...}
    POST /enrol/{user}                -> registers a member (called once by `main.py enrol`)
    POST /approve  {envelope, request} -> {"public": "accepted" | "need_second_approver" | "unavailable"}

Every failure (bad signature, wrong tag, not the registered user's hand, locked) answers the same
"unavailable", so an attacker who tries again and again learns nothing. The real outcome
(execute / hold_and_alert / reject_unknown_hand) goes to `on_outcome`, never back to the requester.
"""
import json
import os
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import mldsa
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import yuseal as ys

RP_ID = os.environ.get("FIDO_RP_ID", "guardian.yuduino.local")
ADDRESS_BOOK = json.loads(os.environ.get("ADDRESS_BOOK", "{}"))  # address -> unique label (org-root signed in Wave 3)

app = FastAPI()
verifier = ys.Verifier(RP_ID, address_book=ADDRESS_BOOK)
outcomes: list[dict] = []  # Wave 1: printed and kept in memory. Wave 3: alerts, Tiger Data, dashboard.


def on_outcome(result: dict, env: dict):
    entry = {"who": env["core"]["who"], "type": env["core"]["type"], "internal": result["internal"],
             "status": result.get("status"), "reason": str(result["reason"])[:200]}
    outcomes.append(entry)
    print("[guardian]", entry)
    if result["internal"] == "hold_and_alert":
        print("[guardian] SILENT ALERT: possible duress for", env["core"]["who"])  # responder._silent_alert in Wave 3


class Enrol(BaseModel):
    yk_pub_der: str = ""  # YubiKey credential public key, base64 (SubjectPublicKeyInfo DER). Empty in HMAC-SHA1 mode
    yk_hmac_key: str = "" # HMAC-SHA1 fallback only: the slot key, base64 (from tools/setup_yk_hmac.py)
    pq_pub: str           # ML-DSA-65 public key, base64
    k_tag: str            # from tools/provision.py
    seed: list[list[int]] = []  # the supervised enrolment click's sensor summary(ies): the first baseline


class Approve(BaseModel):
    envelope: dict
    request: dict


@app.post("/nonce")
def nonce():
    return {"nonce": verifier.new_nonce()}


@app.post("/enrol/{user}")
def enrol(user: str, e: Enrol):
    if user in verifier.members:
        raise HTTPException(409, "already enrolled; revoke first")
    if bool(e.yk_pub_der) == bool(e.yk_hmac_key):
        raise HTTPException(400, "give exactly one of yk_pub_der (FIDO2) or yk_hmac_key (HMAC-SHA1)")
    verifier.members[user] = ys.Member(
        serialization.load_der_public_key(ys.unb64(e.yk_pub_der)) if e.yk_pub_der else None,
        mldsa.MLDSA65PublicKey.from_public_bytes(ys.unb64(e.pq_pub)),
        ys.unb64(e.k_tag),
        ys.unb64(e.yk_hmac_key) if e.yk_hmac_key else None)
    for f in e.seed:
        if len(f) == ys.N_FEATURES:
            verifier.members[user].baseline.add(f, time.gmtime().tm_hour)
    return {"ok": True}


@app.post("/approve")
def approve(a: Approve):
    result = verifier.check(a.envelope, a.request)
    if result["internal"] != "reject":
        on_outcome(result, a.envelope)
    while verifier.alerts:
        print("[guardian] ALERT:", verifier.alerts.pop(0))  # responder._silent_alert in Wave 3
    return {"public": result["public"]}

