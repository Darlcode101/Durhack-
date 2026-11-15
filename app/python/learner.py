"""Learning the user's normal, all day, on the board. Nothing is judged and nothing leaves the device.

Every second, while a palm is on the grip, the STM32 adds its own readings to this hour's rolling
baseline (baseline_add). Every minute the raw samples are boiled down to ONE feature row (the same
vector the Edge Impulse model sees at a transaction, see edge_model.FEATURE_NAMES) and the samples are
discarded. The rows are the user's private training set, stored encrypted (userprofile.py).
Every few minutes the baseline is also saved, encrypted, so it survives a power cut.
"""
from __future__ import annotations

import json
import os
import time

import edge_model as em
import userprofile as up


# The last minute of readings, for the transaction check. RAM only (tmpfs): it is gone at reboot and
# is overwritten every second, so it never holds more than 60 s.
RECENT_PATH = os.environ.get("RECENT_PATH", "/dev/shm/yuduino_recent.json")
WINDOW_S = 60


def save_recent(samples: list[dict], now: float, path: str | None = None) -> None:
    path = path or RECENT_PATH
    keep = [s for s in samples if now - s["t"] <= WINDOW_S]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(keep, f)
    os.replace(tmp, path)


def recent_window(now: float, path: str | None = None) -> list[dict]:
    """The readings of the last minute that the learner recorded (hand on the mouse, no approval in
    progress); [] when it is not running or the file is stale."""
    try:
        with open(path or RECENT_PATH) as f:
            return [s for s in json.load(f) if now - s["t"] <= WINDOW_S]
    except Exception:
        return []


class Learner:
    def __init__(self, bridge, profile: up.Profile, clock=time.time, sleep=time.sleep,
                 minute_s: float = 60, persist_s: float = 300):
        self.bridge, self.profile, self.clock, self.sleep = bridge, profile, clock, sleep
        self.minute_s, self.persist_s = minute_s, persist_s
        self.buf: list[dict] = []
        self.recent: list[dict] = []
        self.rows = 0
        self.added = 0
        self._minute_at = self._persist_at = clock()

    def tick(self) -> None:
        """One second of learning."""
        hour = time.localtime(self.clock()).tm_hour
        try:
            f = json.loads(self.bridge.call("get_features"))
        except Exception:
            return                                     # a dropped reading is just skipped
        if f.get("grip") == 1 and f.get("state") == 0:  # a hand on the mouse, and no approval in progress
            if up.learn_tick(self.bridge, hour):
                self.added += 1
            self.buf.append(f)
            self.recent = [r for r in self.recent if self.clock() - r["t"] <= WINDOW_S] + [{**f, "t": self.clock()}]
            try:
                save_recent(self.recent, self.clock())
            except OSError:
                pass                                   # no tmpfs: the transaction falls back to a live sample
        now = self.clock()
        if now - self._minute_at >= self.minute_s:
            self.flush_minute(hour)
        if now - self._persist_at >= self.persist_s:
            self.persist()

    def flush_minute(self, hour: int | None = None) -> bool:
        """Turn this minute's samples into one training row, then discard them."""
        self._minute_at = self.clock()
        window, self.buf = self.buf, []
        if len(window) < 10:                           # too little hand-on-mouse time to mean anything
            return False
        hour = time.localtime(self.clock()).tm_hour if hour is None else hour
        self.profile.append_training(em.feature_vector(window, up.hour_z(self.bridge, hour)))
        self.rows += 1
        return True

    def persist(self) -> None:
        self._persist_at = self.clock()
        self.profile.persist_baseline(self.bridge)

    def run(self, minutes: float | None = None, progress=None) -> None:
        """Learn for `minutes` (forever if None), saving at the end."""
        end = None if minutes is None else self.clock() + minutes * 60
        try:
            while end is None or self.clock() < end:
                self.tick()
                if progress and self.added and self.added % 30 == 0:
                    progress(self)
                self.sleep(1)
        finally:
            self.flush_minute()
            self.persist()
