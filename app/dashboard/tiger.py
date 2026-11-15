"""Tiger Data (TimescaleDB on Tiger Cloud) storage for the YuDuino dashboard.

What lives in Tiger:
  readings      hypertable, one row per second: verdict, scores, people, sensors, YubiKey
  incidents     hypertable, one row per WATCH/DURESS episode (start, end, peak, reasons)
  readings_1m   continuous aggregate: per-minute history for the 24 h chart
  readings_1h   continuous aggregate: per-hour stats -> "your normal by time of day"
  + compression after 7 days and a 90-day retention policy (keep only what is needed)

Only derived numbers are stored: no camera frames, no PINs, no keys.
Configure with TIGER_DATABASE_URL in .env (the service URL from Tiger Console). Without it the
dashboard still runs live; history panels say Tiger is not connected.
"""
import collections
import os
import threading
import time

URL = os.environ.get("TIGER_DATABASE_URL", "").strip()
DEVICE = os.environ.get("DEVICE_ID", "yuduino-01")
TZ = os.environ.get("DASHBOARD_TZ", "Europe/London")

BASE_COLUMNS = ("time", "device", "verdict", "score", "local_score", "gemini_score", "faces", "close_people",
                "far_people", "humidity", "temp_c", "shake_rms", "moisture", "touch", "sweat_z", "move_z",
                "yubikey", "gemini_latency")
# Extra columns, each written only if the service accepted the ALTER TABLE that adds it.
EXTRA_COLUMNS = [("decision column", ("decided_by",)),                       # "sensors" or "camera"
                 ("assessment columns", ("body_score", "explanation", "baseline"))]  # baseline = jsonb snapshot
COLUMNS = BASE_COLUMNS + tuple(c for _, cols in EXTRA_COLUMNS for c in cols)

SCHEMA = [
    ("readings table", """
     CREATE TABLE IF NOT EXISTS readings (
       time timestamptz NOT NULL, device text NOT NULL, verdict text NOT NULL,
       score real, local_score real, gemini_score real,
       faces smallint, close_people smallint, far_people smallint,
       humidity real, temp_c real, shake_rms real, moisture real, touch boolean,
       sweat_z real, move_z real, yubikey boolean, gemini_latency real)"""),
    ("readings hypertable", "SELECT create_hypertable('readings', by_range('time', INTERVAL '1 day'), if_not_exists => TRUE)"),
    ("readings index", "CREATE INDEX IF NOT EXISTS readings_device_time ON readings (device, time DESC)"),
    ("decision column", "ALTER TABLE readings ADD COLUMN IF NOT EXISTS decided_by text"),
    ("assessment columns", """
     ALTER TABLE readings ADD COLUMN IF NOT EXISTS body_score real,
                          ADD COLUMN IF NOT EXISTS explanation text,
                          ADD COLUMN IF NOT EXISTS baseline jsonb"""),
    ("incident labels", """
     ALTER TABLE incidents ADD COLUMN IF NOT EXISTS label text,
                           ADD COLUMN IF NOT EXISTS labelled_at timestamptz"""),
    ("personal baseline aggregate", """
     CREATE MATERIALIZED VIEW IF NOT EXISTS baseline_1h
     WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
     SELECT time_bucket('1 hour', time) AS bucket, device,
            avg(humidity) AS humidity, stddev_samp(humidity) AS humidity_sd,
            avg(moisture) AS moisture, stddev_samp(moisture) AS moisture_sd,
            avg(shake_rms) AS shake, stddev_samp(shake_rms) AS shake_sd, count(*) AS n
     FROM readings WHERE touch IS TRUE AND verdict = 'NORMAL'
     GROUP BY bucket, device WITH NO DATA"""),
    ("personal baseline refresh policy", """
     SELECT add_continuous_aggregate_policy('baseline_1h', start_offset => INTERVAL '3 days',
            end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)"""),
    ("incidents table", """
     CREATE TABLE IF NOT EXISTS incidents (
       time timestamptz NOT NULL, device text NOT NULL, verdict text NOT NULL,
       peak_score real, signals text[], gemini_reasoning text, ended_at timestamptz)"""),
    ("incidents hypertable", "SELECT create_hypertable('incidents', by_range('time', INTERVAL '30 days'), if_not_exists => TRUE)"),
    ("per-minute continuous aggregate", """
     CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1m
     WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
     SELECT time_bucket('1 minute', time) AS bucket, device,
            avg(score) AS avg_score, max(score) AS max_score, avg(gemini_score) AS avg_gemini,
            avg(humidity) AS humidity, avg(temp_c) AS temp_c, avg(shake_rms) AS shake_rms,
            avg(moisture) AS moisture, max(close_people) AS max_close, count(*) AS n,
            count(*) FILTER (WHERE verdict = 'DURESS') AS duress_n,
            count(*) FILTER (WHERE verdict = 'WATCH') AS watch_n
     FROM readings GROUP BY bucket, device WITH NO DATA"""),
    ("per-minute refresh policy", """
     SELECT add_continuous_aggregate_policy('readings_1m', start_offset => INTERVAL '3 hours',
            end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE)"""),
    ("per-hour continuous aggregate", """
     CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1h
     WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
     SELECT time_bucket('1 hour', time) AS bucket, device,
            avg(humidity) AS humidity, stddev(humidity) AS humidity_sd,
            avg(shake_rms) AS shake_rms, stddev(shake_rms) AS shake_sd,
            avg(moisture) AS moisture, avg(temp_c) AS temp_c, avg(score) AS avg_score,
            count(*) AS n, count(*) FILTER (WHERE verdict = 'NORMAL') AS normal_n
     FROM readings GROUP BY bucket, device WITH NO DATA"""),
    ("per-hour refresh policy", """
     SELECT add_continuous_aggregate_policy('readings_1h', start_offset => INTERVAL '3 days',
            end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)"""),
    ("compression", "ALTER TABLE readings SET (timescaledb.compress, timescaledb.compress_segmentby = 'device')"),
    ("compression policy", "SELECT add_compression_policy('readings', INTERVAL '7 days', if_not_exists => TRUE)"),
    ("90-day retention", "SELECT add_retention_policy('readings', INTERVAL '90 days', if_not_exists => TRUE)"),
]

status = {"enabled": bool(URL), "connected": False, "error": None, "written": 0, "buffered": 0,
          "features": {}, "device": DEVICE}
_queue = collections.deque(maxlen=20000)   # store-and-forward: survives short network drops
_ops = collections.deque(maxlen=500)       # incident inserts/updates, applied in order
_lock = threading.Lock()


def _safe(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}".splitlines()[0]
    return msg.replace(URL, "<url>") if URL else msg   # never leak the password-bearing URL


def _connect():
    import psycopg
    return psycopg.connect(URL, autocommit=True, connect_timeout=10)


def setup(conn):
    """Idempotent: creates whatever is missing; each step is tried independently."""
    feats = {}
    for name, sql in SCHEMA:
        try:
            conn.execute(sql)
            feats[name] = True
        except Exception as e:
            feats[name] = _safe(e)[:160]
    status["features"] = feats


# ------------------------------------------------------------------ writing
def record(row: dict):
    if URL:
        _queue.append(tuple(row.get(c) for c in COLUMNS))
        status["buffered"] = len(_queue)


def incident_open(start_ts: float, verdict: str, score: float, signals: list, reasoning: str | None):
    if URL:
        _ops.append(("open", start_ts, verdict, score, signals, reasoning))


def incident_update(start_ts: float, verdict: str, score: float, signals: list, reasoning: str | None,
                    ended: bool):
    if URL:
        _ops.append(("update", start_ts, verdict, score, signals, reasoning, ended))


def _flush(conn):
    from datetime import datetime, timezone
    rows = []
    while _queue and len(rows) < 2000:
        rows.append(_queue.popleft())
    if rows:
        # Write only the extra columns the service actually accepted.
        keep = list(range(len(BASE_COLUMNS)))
        pos = len(BASE_COLUMNS)
        for feat, cols in EXTRA_COLUMNS:
            if status["features"].get(feat) is True:
                keep += list(range(pos, pos + len(cols)))
            pos += len(cols)
        cols = [COLUMNS[i] for i in keep]
        try:
            with conn.cursor() as cur, cur.copy(f"COPY readings ({', '.join(cols)}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row([r[i] for i in keep])
            status["written"] += len(rows)
        except Exception:
            _queue.extendleft(reversed(rows))   # put them back, retry later
            raise
    while _ops:
        op = _ops[0]
        ts = datetime.fromtimestamp(op[1], timezone.utc)
        if op[0] == "open":
            conn.execute("INSERT INTO incidents (time, device, verdict, peak_score, signals, gemini_reasoning) "
                         "VALUES (%s, %s, %s, %s, %s, %s)", (ts, DEVICE, op[2], op[3], op[4], op[5]))
        else:
            conn.execute("""UPDATE incidents SET
                              verdict = CASE WHEN %s = 'DURESS' THEN 'DURESS' ELSE verdict END,
                              peak_score = GREATEST(peak_score, %s),
                              signals = CASE WHEN %s > peak_score THEN %s ELSE signals END,
                              gemini_reasoning = COALESCE(%s, gemini_reasoning),
                              ended_at = CASE WHEN %s THEN now() ELSE ended_at END
                            WHERE device = %s AND time = %s""",
                         (op[2], op[3], op[3], op[4], op[5], op[6], DEVICE, ts))
        _ops.popleft()
    status["buffered"] = len(_queue)


def writer_loop():
    if not URL:
        return
    conn, backoff = None, 2
    while True:
        try:
            if conn is None or conn.closed:
                conn = _connect()
                setup(conn)
                status.update(connected=True, error=None)
                backoff = 2
            _flush(conn)
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
_qconn = None


def query(sql: str, params=()):
    """Runs a read query on a dedicated connection; returns list of tuples, or raises."""
    global _qconn
    with _lock:
        for attempt in (1, 2):
            try:
                if _qconn is None or _qconn.closed:
                    _qconn = _connect()
                return _qconn.execute(sql, params).fetchall()
            except Exception:
                try:
                    _qconn and _qconn.close()
                except Exception:
                    pass
                _qconn = None
                if attempt == 2:
                    raise


RANGES = {  # range -> (source, bucket, lookback)
    "15m": ("raw", "5 seconds", "15 minutes"),
    "1h": ("raw", "30 seconds", "1 hour"),
    "24h": ("1m", "10 minutes", "24 hours"),
    "7d": ("1m", "1 hour", "7 days"),
}


def history(rng: str) -> dict:
    src, bucket, lookback = RANGES.get(rng, RANGES["15m"])
    if src == "raw":
        sql = f"""SELECT extract(epoch FROM time_bucket('{bucket}', time)) AS t,
                         avg(score), max(score), avg(gemini_score), avg(humidity), avg(shake_rms),
                         avg(moisture), max(close_people)
                  FROM readings WHERE device = %s AND time > now() - INTERVAL '{lookback}'
                  GROUP BY 1 ORDER BY 1"""
    else:
        sql = f"""SELECT extract(epoch FROM time_bucket('{bucket}', bucket)) AS t,
                         avg(avg_score), max(max_score), avg(avg_gemini), avg(humidity), avg(shake_rms),
                         avg(moisture), max(max_close)
                  FROM readings_1m WHERE device = %s AND bucket > now() - INTERVAL '{lookback}'
                  GROUP BY 1 ORDER BY 1"""
    rows = query(sql, (DEVICE,))
    cols = ["t", "score", "max_score", "gemini", "humidity", "shake", "moisture", "close"]
    out = {c: [] for c in cols}
    for r in rows:
        for c, v in zip(cols, r):
            out[c].append(None if v is None else float(v))
    out.update(range=rng, bucket=bucket, source="readings (hypertable)" if src == "raw" else "readings_1m (continuous aggregate)")
    return out


def normal_by_hour() -> dict:
    rows = query(f"""SELECT extract(hour FROM bucket AT TIME ZONE '{TZ}')::int AS h,
                            avg(humidity), avg(shake_rms), avg(temp_c), sum(n)
                     FROM readings_1h WHERE device = %s AND bucket > now() - INTERVAL '14 days'
                       AND normal_n > 0.8 * n
                     GROUP BY 1 ORDER BY 1""", (DEVICE,))
    return {"hours": [{"h": r[0], "humidity": r[1], "shake": r[2], "temp": r[3], "n": int(r[4])} for r in rows],
            "source": "readings_1h (continuous aggregate), calm hours only, last 14 days"}


def incidents(limit: int = 25) -> list:
    # ::float8 because extract() returns numeric (Python Decimal), which JSON can't encode
    lab = status["features"].get("incident labels") is True
    rows = query(f"""SELECT extract(epoch FROM time)::float8, verdict, peak_score, signals, gemini_reasoning,
                            extract(epoch FROM ended_at)::float8, {"label" if lab else "NULL"}
                     FROM incidents WHERE device = %s ORDER BY time DESC LIMIT %s""", (DEVICE, limit))
    return [{"t": r[0], "verdict": r[1], "peak": r[2], "signals": r[3] or [], "reasoning": r[4], "ended": r[5],
             "label": r[6]} for r in rows]


# ------------------------------------------------------------------ learning inputs (all deterministic)
def usual_for_hour(hour: int) -> dict | None:
    """This user's calm, hand-on-mouse normal at this hour of day over the last 14 days, as
    {key: (mean, sd, n)}, pooled from the baseline_1h continuous aggregate."""
    import baseline_model as bm
    rows = query(f"""SELECT humidity, humidity_sd, moisture, moisture_sd, shake, shake_sd, n
                     FROM baseline_1h
                     WHERE device = %s AND bucket > now() - INTERVAL '14 days'
                       AND extract(hour FROM bucket AT TIME ZONE '{TZ}') = %s""", (DEVICE, hour))
    if not rows:
        return None
    return {"humidity": bm.pool([(r[0], r[1], r[6]) for r in rows]),
            "moisture": bm.pool([(r[2], r[3], r[6]) for r in rows]),
            "shake_rms": bm.pool([(r[4], r[5], r[6]) for r in rows])}


def recent_rows(minutes: int = 30) -> list:
    """Hand-on-mouse readings from the last `minutes`, oldest first: (t, humidity, moisture, shake, verdict)."""
    return query(f"""SELECT extract(epoch FROM time)::float8, humidity, moisture, shake_rms, verdict
                     FROM readings WHERE device = %s AND touch IS TRUE AND time > now() - INTERVAL '{int(minutes)} minutes'
                     ORDER BY time""", (DEVICE,))


def false_alarms_near_hour(hour: int) -> int:
    """Incidents labelled false alarms in the last 30 days within an hour of this time of day."""
    if status["features"].get("incident labels") is not True:
        return 0
    return query(f"""SELECT count(*) FROM incidents
                     WHERE device = %s AND label = 'false_alarm' AND time > now() - INTERVAL '30 days'
                       AND abs(extract(hour FROM time AT TIME ZONE '{TZ}') - %s) <= 1""", (DEVICE, hour))[0][0]


def label_incident(t: float, label: str) -> bool:
    """Mark an incident (by its start time) as 'false_alarm' or 'confirmed'. In a real deployment
    only compliance/security would be allowed to do this, because labels widen tolerance."""
    if label not in ("false_alarm", "confirmed", None):
        raise ValueError("label must be false_alarm, confirmed or null")
    from datetime import datetime, timezone
    rows = query("""UPDATE incidents SET label = %s, labelled_at = now()
                    WHERE device = %s AND time = %s RETURNING 1""",
                 (label, DEVICE, datetime.fromtimestamp(t, timezone.utc)))
    return bool(rows)


def stats() -> dict:
    r = query("""SELECT
                   (SELECT count(*) FROM readings WHERE device = %s AND time > now() - INTERVAL '24 hours'),
                   (SELECT count(*) FROM incidents WHERE device = %s AND time > now() - INTERVAL '24 hours'),
                   (SELECT count(*) FROM incidents WHERE device = %s AND verdict = 'DURESS'
                                                      AND time > now() - INTERVAL '24 hours'),
                   (SELECT count(*) FROM readings),   -- exact; approximate_row_count lags until ANALYZE
                   (SELECT hypertable_size('readings')),
                   (SELECT min(time) FROM readings WHERE device = %s)""", (DEVICE,) * 3 + (DEVICE,))[0]
    return {"readings_24h": r[0], "incidents_24h": r[1], "duress_24h": r[2], "total_rows": r[3],
            "size_bytes": r[4], "since": r[5].timestamp() if r[5] else None}
