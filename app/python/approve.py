"""The Linux side of one YuSeal approval, and of enrolment. See docs/BUILD-FLOW.md.

Zero-input mouse mode: nobody does anything but click. Everything outside this file is injected,
so the same code runs on the board (real Bridge, real YubiKey) and in tests (fake STM32, soft YubiKey).

    bridge    .call(name, *args) -> str          the STM32 (arm_approval, get_unlock_salt, get_attest,
                                                 get_features, seal_approval)
    yk        .register(user), .assert_and_secret(rp_id, challenge, salt)

YuDuino is only the authenticator. The customer's system sends a request and a nonce (from
`Verifier.new_nonce()` in yuseal.py), and gets back an envelope to verify with `Verifier.check()`.

Flow: a request arrives -> the person's ordinary click on "process transaction" is on the STM32's
switch tap -> arm the STM32 with the approval's digest (it refuses unless a real click with the
palm on the grip came within 1.5 s) -> salt -> YubiKey -> on-device model -> STM32 seals -> envelope.
Linux never learns the duress result: it gets an opaque tag it can't read.
"""
from __future__ import annotations

import json
import math
import os
import time

import yuseal as ys
from userprofile import hour_z


class Refused(Exception):
    """No real click arrived, or the STM32 would not arm or seal. Nothing was signed."""


# ---------------------------------------------------------------- state on the Linux side
class DeviceState:
    """credential, wrapped ML-DSA key, audit log. Saved after every change.

    Nothing in here is enough to approve anything: the ML-DSA key is wrapped under the YubiKey
    secret, whose salt only the STM32 releases, and only after a real click."""

    def __init__(self, path: str):
        self.path = path
        self.data = json.load(open(path)) if os.path.exists(path) else {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- the sensors' own veto
def onboard_veto(window: list[dict]) -> bool:
    """Extreme or missing readings mean the sensors can't be trusted: that is duress (fail closed)."""
    if not window:
        return True
    for f in window:
        for k, lo, hi in (("temp_c", -20, 60), ("humidity", 0, 100), ("shake_rms", 0, 50), ("moisture", 0, 4095)):
            v = f.get(k)
            if not isinstance(v, (int, float)) or math.isnan(v) or not lo <= v <= hi:
                return True
    return False


# ---------------------------------------------------------------- arming on a real click
def _arm_on_click(bridge, digest: bytes, sleep, timeout_s: float) -> None:
    """Poll until the STM32 accepts the arm: that needs a real click with a palm on the grip in the
    last 1.5 s. A request that arrives with no click waits for the person's click, then times out."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if bridge.call("arm_approval", digest.hex()) == "1":
            return
        sleep(0.1)
    raise Refused("no real click (with a hand on the mouse) in time")


def _collect_window(bridge, sleep, n: int = 5, gap_s: float = 0.1) -> list[dict]:
    window = []
    for _ in range(n):
        window.append(json.loads(bridge.call("get_features")))
        sleep(gap_s)
    return window


def _attest(bridge) -> bytes:
    raw = bridge.call("get_attest")
    if raw == "-":
        raise Refused("STM32 session ended")
    return bytes.fromhex(raw)


def _salt(bridge) -> bytes:
    salt = bridge.call("get_unlock_salt")
    if salt == "-":
        raise Refused("STM32 not armed")
    return bytes.fromhex(salt)


# ---------------------------------------------------------------- enrolment
def enrol(*, bridge, yk, state: DeviceState, user: str, device: str, rp_id: str,
          sleep=time.sleep, timeout_s: float = 90):
    """One person, in person, with a second team member watching.

    Needs the sketch flashed with the secrets from tools/provision.py. The person just clicks
    once; that first click's sensor summary seeds their baseline (this supervised sample is the
    only one the verifier takes without an owner check). Returns the enrolment package for the
    verifier (public data only).
    """
    credential, yk_pub = yk.register(user)
    zero = bytes(32)
    _arm_on_click(bridge, zero, sleep, timeout_s)
    salt = _salt(bridge)
    attest = _attest(bridge)
    _, secret = yk.assert_and_secret(rp_id, zero, salt)
    bridge.call("seal_approval", "0", "0")  # finishes the STM32's session
    store, pq_key = ys.create_keystore(secret)
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    state.data.update(user=user, device=device, credential=ys.b64(credential), keystore=store, log=[],
                      pq_pub=ys.b64(pq_key.public_key().public_bytes_raw()))
    state.save()
    _, _, seed = ys.parse_attest(attest)
    body = {"yk_pub_der": "", "pq_pub": ys.b64(pq_key.public_key().public_bytes_raw()),
            "seed": [seed]}  # the caller adds k_tag (and yk_hmac_key in HMAC mode)
    if yk_pub is not None:
        body["yk_pub_der"] = ys.b64(yk_pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo))
    return body


# ---------------------------------------------------------------- one approval
def approve(*, bridge, yk, state: DeviceState, request: dict, nonce: str, rp_id: str,
            model_fn=lambda window, context=None: None, sleep=time.sleep, timeout_s: float = 5) -> dict:
    """Returns {"envelope": the envelope}, for the customer's verifier to check.

    Duress is judged only here, at the moment of a transaction; nothing runs continuously.

    `model_fn(window, context)` takes the sensor readings sampled right after the click and returns the
    on-device Edge Impulse model's dict (see edge_model.py), or None, which fails closed to duress.
    Only the model scores; the STM32 decides and tags.
    """
    user, device = state.data["user"], state.data["device"]
    core = ys.build_core(request, service=rp_id, approver=user, device=device, nonce=nonce)
    digest = ys.core_digest(core)

    _arm_on_click(bridge, digest, sleep, timeout_s)
    salt = _salt(bridge)
    attest = _attest(bridge)
    assertion, secret = yk.assert_and_secret(rp_id, digest, salt)   # no touch in mouse mode
    pq_key = ys.unlock(state.data["keystore"], secret)
    if pq_key is None:
        raise Refused("wrong YubiKey")
    window = _collect_window(bridge, sleep)
    verdict = model_fn(window, hour_z(bridge, time.localtime().tm_hour))   # may be None: fails closed
    score = ys.model_to_score(verdict)
    veto = onboard_veto(window)
    tag = bridge.call("seal_approval", str(score), "1" if veto else "0")
    if tag == "-":
        raise Refused("STM32 would not seal (session ended)")

    log = state.data["log"]
    prev = log[-1]["hash"] if log else ys.GENESIS
    env = ys.make_envelope(core, assertion, bytes.fromhex(tag), attest, prev, pq_key)
    ys.log_append(log, env, pq_key)
    state.save()
    del pq_key, secret
    return {"envelope": env}
