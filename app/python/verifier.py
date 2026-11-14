"""Demo verifier — stands in for the "door" or service that receives access tokens.

It only holds the two PUBLIC keys. A token signed with the duress key verifies
as valid (so an attacker watching sees success), but the verifier knows to alert.
"""
import base64
import json

SIG_ALG = "ML-DSA-65"


def verify(token: dict, public_keys: dict) -> str:
    """Returns "valid", "valid_duress", or "invalid"."""
    import oqs

    claims = base64.b64decode(token["claims"])
    sig = base64.b64decode(token["sig"])
    with oqs.Signature(SIG_ALG) as v:
        if v.verify(claims, sig, base64.b64decode(public_keys["normal"])):
            return "valid"
        if v.verify(claims, sig, base64.b64decode(public_keys["duress"])):
            return "valid_duress"
    return "invalid"


def claims(token: dict) -> dict:
    return json.loads(base64.b64decode(token["claims"]))
