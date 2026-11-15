"""The user's profile at rest: the all-day baseline and the Edge Impulse model weights.

Everything is encrypted with AES-256-GCM (symmetric, so quantum-resistant) under a key the STM32
derives from its own secret (`get_profile_key`). The key is never written to the board's Linux
side, so a stolen board gives an attacker only ciphertext. Nothing is ever sent off the device.

    PROFILE_DIR   where the encrypted files live (default app/python/profile/, gitignored)

Files: baseline.bin (24 hours of per-sensor rolling statistics, from the STM32) and
model-<user>.eim (the user's Edge Impulse anomaly model), each stored as  b"YP1" | nonce | AES-GCM.
The file name is bound in as associated data, so one file cannot be swapped for another.
"""
from __future__ import annotations

import os
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import yuseal as ys

MAGIC = b"YP1"
PROFILE_DIR = os.environ.get("PROFILE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile")


class Profile:
    """`key_fn()` returns the 32-byte profile key (from the STM32). Fetched lazily, held only in memory."""

    def __init__(self, key_fn, directory: str | None = None):
        self.key_fn, self.dir, self._key = key_fn, directory or PROFILE_DIR, None

    @classmethod
    def from_bridge(cls, bridge, directory: str | None = None) -> "Profile":
        return cls(lambda: bytes.fromhex(bridge.call("get_profile_key")), directory)

    def _aead(self) -> AESGCM:
        if self._key is None:
            key = self.key_fn()
            if not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("no usable profile key from the STM32")
            self._key = key
        return AESGCM(self._key)

    def _path(self, name: str) -> str:
        if "/" in name or name.startswith("."):
            raise ValueError("bad profile file name")
        return os.path.join(self.dir, name)

    def save(self, name: str, data: bytes) -> None:
        nonce = os.urandom(12)
        blob = MAGIC + nonce + self._aead().encrypt(nonce, data, name.encode())
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        tmp = self._path(name) + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
            f.write(blob)
        os.replace(tmp, self._path(name))

    def has(self, name: str) -> bool:
        return os.path.exists(self._path(name))

    def load(self, name: str) -> bytes | None:
        """The plaintext, or None if there is no such file, it was tampered with, or the key is wrong."""
        try:
            raw = open(self._path(name), "rb").read()
        except FileNotFoundError:
            return None
        if raw[:3] != MAGIC or len(raw) < 3 + 12 + 16:
            return None
        try:
            return self._aead().decrypt(raw[3:15], raw[15:], name.encode())
        except InvalidTag:
            return None

    # ---- the baseline (STM32 <-> encrypted copy on Linux)
    def persist_baseline(self, bridge) -> None:
        """Copy the STM32's 24 hours of rolling statistics into one encrypted file."""
        parts = []
        for hour in range(ys.BL_HOURS):
            raw = bytes.fromhex(bridge.call("baseline_export", str(hour)))
            if len(raw) != ys.BL_HOUR_BYTES:
                raise ValueError(f"bad baseline export for hour {hour}")
            parts.append(raw)
        self.save("baseline.bin", b"".join(parts))

    def restore_baseline(self, bridge) -> int:
        """Load the encrypted copy back into the STM32 after a power cut. Returns hours restored."""
        data = self.load("baseline.bin")
        if data is None or len(data) != ys.BL_HOURS * ys.BL_HOUR_BYTES:
            return 0
        ok = 0
        for hour in range(ys.BL_HOURS):
            chunk = data[hour * ys.BL_HOUR_BYTES:(hour + 1) * ys.BL_HOUR_BYTES]
            ok += bridge.call("baseline_import", str(hour), chunk.hex()) == "1"
        return ok

    # ---- the training rows (per-minute feature vectors, raw samples already discarded)
    def append_training(self, row: list[float]) -> None:
        import json
        rows = self.training_rows()
        rows.append([round(float(x), 6) for x in row])
        self.save("training.bin", json.dumps(rows).encode())

    def training_rows(self) -> list[list[float]]:
        import json
        raw = self.load("training.bin")
        return json.loads(raw) if raw else []

    # ---- the model
    def import_model(self, user: str, eim_path: str) -> None:
        """Encrypt an exported Edge Impulse .eim file into the profile. Delete the plaintext afterwards."""
        self.save(f"model-{user}.eim", open(eim_path, "rb").read())

    def open_model(self, user: str) -> str | None:
        """Decrypt the user's model into RAM (tmpfs) as an executable and return its path. The caller
        starts it and then deletes the file at once: a running program keeps working after unlink."""
        data = self.load(f"model-{user}.eim")
        if data is None:
            return None
        base = "/dev/shm" if os.path.isdir("/dev/shm") else None
        fd, path = tempfile.mkstemp(prefix="yp-", suffix=".eim", dir=base)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(path, 0o700)
        return path


def learn_tick(bridge, hour: int) -> bool:
    """Ask the STM32 to add its own current readings to this hour's baseline. It only does so while a
    palm is on the grip, and Linux cannot supply the numbers, only the hour."""
    return bridge.call("baseline_add", str(hour)) == "1"


HOUR_Z_KEYS = ("hour_z_humidity", "hour_z_moisture", "hour_z_shake", "hour_z_temp")


def hour_z(bridge, hour: int) -> dict:
    """The STM32's z-scores of its current readings against this hour's baseline, by feature name.
    Empty if the baseline is too thin for this hour (the model then sees zeros)."""
    try:
        raw = bridge.call("baseline_z", str(hour))
        vals = [float(x) for x in raw.split()]
    except Exception:
        return {}
    return dict(zip(HOUR_Z_KEYS, vals)) if len(vals) == len(HOUR_Z_KEYS) else {}
