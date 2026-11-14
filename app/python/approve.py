"""The Linux side of one YuSeal approval, and of enrolment. See docs/BUILD-FLOW.md.

Everything outside this file is injected, so the same code runs on the board (real Bridge,
real YubiKey, HTTP guardian) and in tests (fake STM32, soft YubiKey, in-process guardian).

    bridge    .call(name, *args) -> str          the STM32 (begin_approval, get_unlock_salt, ...)
    yk        .register(user), .assert_and_secret(rp_id, challenge, salt)
    guardian  .nonce(), .approve(envelope, request), .enrol(user, body)

Linux never sees the PIN and never learns the duress result: it gets a salt only after a
correct PIN, and an opaque tag it can't read.
"""
from __future__ import annotations

import json
import math
import os
import time

import yuseal as ys


class Refused(Exception):
    """The device won't show this request, or no correct PIN arrived. Nothing was signed."""


# ---------------------------------------------------------------- guardian clients
class HttpGuardian:
    """post(path, json) -> dict. On the board: lambda p, j: requests.post(BASE + p, json=j, timeout=5).json()."""

    def __init__(self, post):
        self._post = post

    def nonce(self) -> str:
        return self._post("/nonce", {})["nonce"]

    def approve(self, envelope: dict, request: dict) -> str:
        return self._post("/approve", {"envelope": envelope, "request": request})["public"]

    def enrol(self, user: str, body: dict):
        return self._post(f"/enrol/{user}", body)


# ---------------------------------------------------------------- state on the Linux side
class DeviceState:
    """credential, wrapped ML-DSA key, audit log. Saved after every change.

    Nothing in here is enough to approve anything: the ML-DSA key is wrapped under the YubiKey
    secret and the STM32's PIN-gated salt."""

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


# ---------------------------------------------------------------- enrolment
def enrol(*, bridge, yk, guardian, state: DeviceState, user: str, device: str, rp_id: str,
          sleep=time.sleep, timeout_s: float = 90):
    """One person, in person, with a second team member watching.

    Needs the sketch flashed with the secrets from tools/provision.py, and the guardian
    running. The person enters their (normal) PIN once so the STM32 releases the salt.
    """
    credential, yk_pub = yk.register(user)
    zero = bytes(32)
    if bridge.call("begin_approval", f"ENROL {user}".upper()[:40], zero.hex()) != "1":
        raise Refused("device refused the enrolment text")
    salt = _wait_for_salt(bridge, sleep, timeout_s)
    _, secret = yk.assert_and_secret(rp_id, zero, bytes.fromhex(salt))  # one touch
    bridge.call("seal_approval", "0", "0")  # finishes the STM32's session
    store, pq_key = ys.create_keystore(secret)
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    state.data.update(user=user, device=device, credential=ys.b64(credential), keystore=store, log=[],
                      pq_pub=ys.b64(pq_key.public_key().public_bytes_raw()))
    state.save()
    return {"yk_pub_der": ys.b64(yk_pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)),
            "pq_pub": ys.b64(pq_key.public_key().public_bytes_raw())}  # the caller adds k_tag from tools/out/guardian_tag_key.json and POSTs it


def _wait_for_salt(bridge, sleep, timeout_s, window: list | None = None) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        salt = bridge.call("get_unlock_salt")
        if salt != "-":
            return salt
        feats = json.loads(bridge.call("get_features"))
        if window is not None:
            window.append(feats)
        if feats.get("state") in (0, 3):  # idle again (wrong PIN or timeout) or locked
            raise Refused("no correct PIN" if feats.get("state") == 0 else "device locked")
        sleep(0.2)
    raise Refused("timed out waiting for the PIN")


# ---------------------------------------------------------------- one approval
def approve(*, bridge, yk, guardian, state: DeviceState, request: dict, address_book: dict, rp_id: str,
            gemini_fn=lambda window: None, sleep=time.sleep, timeout_s: float = 90) -> dict:
    """Returns {"public": what the requester may be told, "envelope": the envelope}.

    `gemini_fn(window)` takes the sensor readings collected while the PIN was typed and returns
    fusion_gemini's dict (or None). It is called only AFTER a correct PIN, and never receives the PIN.
    """
    user, device = state.data["user"], state.data["device"]
    nonce = guardian.nonce()
    core, text = ys.build_core(request, address_book, service=rp_id, approver=user, device=device, nonce=nonce)
    digest = ys.core_digest(core)

    if bridge.call("begin_approval", text, digest.hex()) != "1":    # STM32 shows the text
        raise Refused("device refused to show this request")
    window: list[dict] = []
    salt = bytes.fromhex(_wait_for_salt(bridge, sleep, timeout_s, window))   # person presses PIN

    assertion, secret = yk.assert_and_secret(rp_id, digest, salt)   # person touches the YubiKey
    pq_key = ys.unlock(state.data["keystore"], secret)
    if pq_key is None:
        raise Refused("wrong YubiKey")
    gemini = gemini_fn(window)                                      # may be None: fails closed
    score = ys.gemini_to_score(gemini)
    veto = onboard_veto(window)
    tag = bridge.call("seal_approval", str(score), "1" if veto else "0")
    if tag == "-":
        raise Refused("STM32 would not seal (session ended)")

    log = state.data["log"]
    prev = log[-1]["hash"] if log else ys.GENESIS
    env = ys.make_envelope(core, assertion, bytes.fromhex(tag), prev, pq_key)
    ys.log_append(log, env, pq_key)
    state.save()
    del pq_key, secret
    return {"public": guardian.approve(env, request), "envelope": env}
