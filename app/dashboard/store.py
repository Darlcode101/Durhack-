"""The dashboard's local store. Everything stays on the board: one SQLite file, nothing sent anywhere.

This module is the whole interface the dashboard uses (record, record_approval, incident_open,
incident_update, label_incident, history, normal_by_hour, incidents, usual_for_hour, recent_rows,
false_alarms_near_hour, stats, writer_loop). It is deliberately small so the storage behind it can
be swapped without touching server.py.

    STORE_PATH   the database file (default app/dashboard/data/yuduino.db, gitignored)
    DEVICE_ID    label stored with every row
"""
from __future__ import annotations

import collections
import math
import os
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

PATH = os.environ.get("STORE_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yuduino.db")
DEVICE = os.environ.get("DEVICE_ID", "yuduino-01")
TZ = os.environ.get("DASHBOARD_TZ", "Europe/London")
RETENTION_DAYS = 90

COLUMNS = ("time", "device", "verdict", "score", "local_score", "edge_score", "faces", "close_people",
           "far_people", "humidity", "temp_c", "shake_rms", "moisture", "touch", "sweat_z", "move_z",
           "yubikey", "edge_latency", "decided_by", "body_score", "explanation", "baseline", "mode")

SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS readings (
          time REAL NOT NULL, device TEXT NOT NULL, verdict TEXT NOT NULL,
          score REAL, local_score REAL, edge_score REAL, faces INTEGER, close_people INTEGER,
          far_people INTEGER, humidity REAL, temp_c REAL, shake_rms REAL, moisture REAL, touch INTEGER,
          sweat_z REAL, move_z REAL, yubikey INTEGER, edge_latency REAL, decided_by TEXT,
          body_score REAL, explanation TEXT, baseline TEXT, mode TEXT)""",
    "CREATE INDEX IF NOT EXISTS readings_device_time ON readings (device, time DESC)",
    """CREATE TABLE IF NOT EXISTS approvals (
          time REAL NOT NULL, device TEXT NOT NULL, label TEXT, verdict TEXT NOT NULL, score REAL,
          decided_by TEXT, body_score REAL, signals TEXT, explanation TEXT, edge_reasoning TEXT, seconds REAL)""",
    """CREATE TABLE IF NOT EXISTS incidents (
          time REAL NOT NULL, device TEXT NOT NULL, verdict TEXT NOT NULL, peak_score REAL, signals TEXT,
          edge_reasoning TEXT, ended_at REAL, label TEXT, labelled_at REAL)""",
]

status = {"enabled": True, "connected": False, "error": None, "written": 0, "buffered": 0,
          "path": PATH, "device": DEVICE}
_queue = collections.deque(maxlen=20000)   # readings waiting for the writer thread
_ops = collections.deque(maxlen=500)       # incident and approval writes, applied in order
_lock = threading.Lock()


def _safe(e: Exception) -> str:
    return f"{type(e).__name__}: {e}".splitlines()[0]


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    conn = sqlite3.connect(PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _setup(conn: sqlite3.Connection):
    for sql in SCHEMA:
        conn.execute(sql)
    conn.commit()


# ------------------------------------------------------------------ writing
def record(row: dict):
    _queue.append(tuple(row.get(c) for c in COLUMNS))
    status["buffered"] = len(_queue)


def incident_open(start_ts: float, verdict: str, score: float, signals: list, reasoning: str | None):
    _ops.append(("open", start_ts, verdict, score, signals, reasoning))


def incident_update(start_ts: float, verdict: str, score: float, signals: list, reasoning: str | None,
                    ended: bool):
    _ops.append(("update", start_ts, verdict, score, signals, reasoning, ended))


def record_approval(t: float, label: str | None, result: dict):
    """One row per transaction check."""
    _ops.append(("approval", t, label, result))


def _ts(v):
    """The server hands over aware datetimes for readings; the store keeps epoch seconds."""
    return v.timestamp() if isinstance(v, datetime) else v


def _flush(conn: sqlite3.Connection):
    rows = []
    while _queue and len(rows) < 2000:
        rows.append(_queue.popleft())
    if rows:
        out = []
        for r in rows:
            r = list(r)
            r[0] = _ts(r[0])
            for i in (13, 16):                       # touch, yubikey: booleans
                r[i] = None if r[i] is None else int(bool(r[i]))
            out.append(r)
        try:
            conn.executemany(f"INSERT INTO readings ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", out)
            conn.commit()
            status["written"] += len(rows)
        except Exception:
            _queue.extendleft(reversed(rows))        # put them back, retry later
            raise
    import json
    while _ops:
        op = _ops[0]
        if op[0] == "approval":
            r = op[3]
            conn.execute("""INSERT INTO approvals (time, device, label, verdict, score, decided_by, body_score,
                              signals, explanation, edge_reasoning, seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (op[1], DEVICE, op[2], r["verdict"], r["score"], r["decided_by"], r.get("body_score"),
                          json.dumps(r.get("signals") or []), r.get("explanation"), r.get("reasoning"), r.get("seconds")))
        elif op[0] == "open":
            conn.execute("INSERT INTO incidents (time, device, verdict, peak_score, signals, edge_reasoning) "
                         "VALUES (?,?,?,?,?,?)", (op[1], DEVICE, op[2], op[3], json.dumps(op[4]), op[5]))
        else:
            cur = conn.execute("SELECT peak_score FROM incidents WHERE device = ? AND time = ?", (DEVICE, op[1])).fetchone()
            if cur:
                peak = cur[0] if cur[0] is not None else 0
                conn.execute("""UPDATE incidents SET
                                  verdict = CASE WHEN ? = 'DURESS' THEN 'DURESS' ELSE verdict END,
                                  peak_score = MAX(peak_score, ?),
                                  signals = CASE WHEN ? > ? THEN ? ELSE signals END,
                                  edge_reasoning = COALESCE(?, edge_reasoning),
                                  ended_at = CASE WHEN ? THEN ? ELSE ended_at END
                                WHERE device = ? AND time = ?""",
                             (op[2], op[3], op[3], peak, json.dumps(op[4]), op[5], int(op[6]), time.time(), DEVICE, op[1]))
        conn.commit()
        _ops.popleft()
    status["buffered"] = len(_queue)


def writer_loop():
    conn, backoff, last_prune = None, 2, 0.0
    while True:
        try:
            if conn is None:
                conn = _connect()
                _setup(conn)
                status.update(connected=True, error=None)
                backoff = 2
            _flush(conn)
            if time.time() - last_prune > 3600:
                last_prune = time.time()
                conn.execute("DELETE FROM readings WHERE time < ?", (time.time() - RETENTION_DAYS * 86400,))
                conn.commit()
            time.sleep(2)
        except Exception as e:
            status.update(connected=False, error=_safe(e))
            try:
                conn and conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


# ------------------------------------------------------------------ reading (for the dashboard)
def query(sql: str, params=()):
    with _lock:
        conn = _connect()
        try:
            _setup(conn)
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


RANGES = {"15m": (5, 900), "1h": (30, 3600), "24h": (600, 86400), "7d": (3600, 604800)}  # bucket s, lookback s


def history(rng: str) -> dict:
    bucket, lookback = RANGES.get(rng, RANGES["15m"])
    rows = query("""SELECT CAST(time / ? AS INTEGER) * ? AS t, avg(score), max(score), avg(edge_score),
                           avg(humidity), avg(shake_rms), avg(moisture), max(close_people)
                    FROM readings WHERE device = ? AND time > ? GROUP BY 1 ORDER BY 1""",
                 (bucket, bucket, DEVICE, time.time() - lookback))
    cols = ["t", "score", "max_score", "edge", "humidity", "shake", "moisture", "close"]
    out = {c: [] for c in cols}
    for r in rows:
        for c, v in zip(cols, r):
            out[c].append(None if v is None else float(v))
    out.update(range=rng, bucket=f"{bucket} seconds", source="readings (local store)")
    return out


def _hour(epoch: float) -> int:
    return datetime.fromtimestamp(epoch, ZoneInfo(TZ)).hour


def normal_by_hour() -> dict:
    rows = query("""SELECT CAST(time / 3600 AS INTEGER) * 3600, avg(humidity), avg(shake_rms), avg(temp_c),
                           count(*), sum(verdict = 'NORMAL')
                    FROM readings WHERE device = ? AND time > ? GROUP BY 1""",
                 (DEVICE, time.time() - 14 * 86400))
    by = {}
    for b, hum, shake, temp, n, normal_n in rows:
        if normal_n and normal_n > 0.8 * n:               # calm hours only
            by.setdefault(_hour(b), []).append((hum, shake, temp, n))
    hours = []
    for h in sorted(by):
        g = by[h]
        avg = lambda i: (sum(x[i] for x in g if x[i] is not None) / max(1, sum(1 for x in g if x[i] is not None))
                         if any(x[i] is not None for x in g) else None)
        hours.append({"h": h, "humidity": avg(0), "shake": avg(1), "temp": avg(2), "n": int(sum(x[3] for x in g))})
    return {"hours": hours, "source": "local store, calm hours only, last 14 days"}


def incidents(limit: int = 25) -> list:
    import json
    rows = query("""SELECT time, verdict, peak_score, signals, edge_reasoning, ended_at, label
                    FROM incidents WHERE device = ? ORDER BY time DESC LIMIT ?""", (DEVICE, limit))
    return [{"t": r[0], "verdict": r[1], "peak": r[2], "signals": json.loads(r[3]) if r[3] else [],
             "reasoning": r[4], "ended": r[5], "label": r[6]} for r in rows]


# ------------------------------------------------------------------ learning inputs (all deterministic)
def usual_for_hour(hour: int) -> dict | None:
    """This user's calm, hand-on-mouse normal at this hour of day over the last 14 days, as
    {key: (mean, sd, n)}, pooled from hourly aggregates."""
    import baseline_model as bm

    def stats_of(col):
        rows = query(f"""SELECT CAST(time / 3600 AS INTEGER) * 3600, avg({col}), avg({col} * {col}), count({col})
                         FROM readings WHERE device = ? AND touch = 1 AND time > ? AND {col} IS NOT NULL
                           AND (mode IS NOT 'approval' OR verdict = 'NORMAL') GROUP BY 1""",
                     (DEVICE, time.time() - 14 * 86400))
        out = []
        for b, mean, sq, n in rows:
            if _hour(b) == hour and n:
                var = max(0.0, (sq - mean * mean) * n / (n - 1)) if n > 1 else 0.0
                out.append((mean, math.sqrt(var), n))
        return out

    h, m, s = stats_of("humidity"), stats_of("moisture"), stats_of("shake_rms")
    if not (h or m or s):
        return None
    return {"humidity": bm.pool(h), "moisture": bm.pool(m), "shake_rms": bm.pool(s)}


def recent_rows(minutes: int = 30) -> list:
    """Hand-on-mouse readings from the last `minutes`, oldest first:
    (t, humidity, moisture, shake, verdict, mode)."""
    return query("""SELECT time, humidity, moisture, shake_rms, verdict, mode FROM readings
                    WHERE device = ? AND touch = 1 AND time > ? ORDER BY time""",
                 (DEVICE, time.time() - int(minutes) * 60))


def false_alarms_near_hour(hour: int) -> int:
    """Incidents labelled false alarms in the last 30 days within an hour of this time of day."""
    rows = query("SELECT time FROM incidents WHERE device = ? AND label = 'false_alarm' AND time > ?",
                 (DEVICE, time.time() - 30 * 86400))
    return sum(1 for (t,) in rows if min(abs(_hour(t) - hour), 24 - abs(_hour(t) - hour)) <= 1)


def label_incident(t: float, label: str | None) -> bool:
    """Mark an incident (by its start time) as 'false_alarm' or 'confirmed'. In a real deployment
    only compliance/security would be allowed to do this, because labels widen tolerance."""
    if label not in ("false_alarm", "confirmed", None):
        raise ValueError("label must be false_alarm, confirmed or null")
    with _lock:
        conn = _connect()
        try:
            _setup(conn)
            cur = conn.execute("UPDATE incidents SET label = ?, labelled_at = ? WHERE device = ? AND time = ?",
                               (label, time.time(), DEVICE, t))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def stats() -> dict:
    now = time.time()
    r = query("""SELECT (SELECT count(*) FROM readings WHERE device = ? AND time > ?),
                        (SELECT count(*) FROM incidents WHERE device = ? AND time > ?),
                        (SELECT count(*) FROM incidents WHERE device = ? AND verdict = 'DURESS' AND time > ?),
                        (SELECT count(*) FROM readings), (SELECT min(time) FROM readings WHERE device = ?)""",
              (DEVICE, now - 86400, DEVICE, now - 86400, DEVICE, now - 86400, DEVICE))[0]
    return {"readings_24h": r[0], "incidents_24h": r[1], "duress_24h": r[2], "total_rows": r[3],
            "size_bytes": os.path.getsize(PATH) if os.path.exists(PATH) else 0, "since": r[4]}
