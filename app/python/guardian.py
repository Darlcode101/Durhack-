"""The guardian: the only route to "execute". Run on Vultr (or on the laptop for Wave 1).

    uvicorn guardian:app --host 0.0.0.0 --port 8000      (put HTTPS in front on Vultr)

Holds only PUBLIC keys and the tag key for each device, so if it is hacked it can refuse
or leak alarms but can't make an approval. Wave 1 keeps its state in memory (a restart means
re-enrolling); Wave 3 persists it.

    POST /nonce                       -> {"nonce": ...}
    POST /enrol/{user}                -> registers a member (called once by `main.py enrol`)
    POST /approve  {envelope, request} -> {"public": "accepted" | "need_second_approver" | "rejected"}

The real outcome (execute / hold_and_alert) goes to `on_outcome`, never back to the requester.
"""
import json
import os

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
    yk_pub_der: str       # YubiKey credential public key, base64 (SubjectPublicKeyInfo DER)
    pq_pub: str           # ML-DSA-65 public key, base64
    k_tag: str            # from tools/provision.py
    seal_msg: dict        # hybrid ML-KEM + X25519 message from the device


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
    kem, x = _guardian_keys()
    verifier.members[user] = ys.Member(
        serialization.load_der_public_key(ys.unb64(e.yk_pub_der)),
        mldsa.MLDSA65PublicKey.from_public_bytes(ys.unb64(e.pq_pub)),
        ys.unb64(e.k_tag),
        ys.SealChain(ys.seal_root_guardian_side(e.seal_msg, kem, x)))
    return {"ok": True}


@app.post("/enrol-keys")
def enrol_keys():
    kem, x = _guardian_keys()
    return {"kem_pub": ys.b64(kem.public_key().public_bytes_raw()),
            "x_pub": ys.b64(x.public_key().public_bytes_raw())}


@app.post("/approve")
def approve(a: Approve):
    result = verifier.check(a.envelope, a.request)
    if result["internal"] != "reject":
        on_outcome(result, a.envelope)
    return {"public": result["public"]}


_keys = {}


def _guardian_keys():
    """ML-KEM-768 and X25519 keys for enrolment. Wave 1: in memory (restart = re-enrol).
    Wave 3: persisted with the state file."""
    if not _keys:
        _keys["kem"] = ys.mlkem.MLKEM768PrivateKey.generate()
        _keys["x"] = ys.x25519.X25519PrivateKey.generate()
    return _keys["kem"], _keys["x"]
