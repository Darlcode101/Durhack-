"""YuDuino live duress monitor (test dashboard). Runs on the UNO Q's Linux side, in the venv.

    ~/durhack-venv/bin/python app/dashboard/server.py      then open http://<board-ip>:8080

Inputs, all passive (no buttons, no user input):
  * camera: is anyone besides the user in view? (largest face = user, any other face = someone else)
  * sensors (STM32 -> App Lab relay -> live/features.json): sweat (moisture + palm humidity),
    movement (Modulino Movement shake), grip (touch), palm temperature
  * YubiKey: plugged in or not (presence only; no touch is requested)
  * Edge Impulse model, on the board: ONLY during a transaction, and only when the sensors are unsure:
    a summary of the above -> duress score. Nothing is sent anywhere. Everyday use is learned from,
    never judged or flagged.

Sensor signals are judged against the user's OWN normal, learned for 30 s at start (or on
"Learn my normal"). Frames are kept in memory only, never written to disk.
"""
import collections
import json
from datetime import datetime, timezone
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "app", "python"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

import cv2  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import edge_model  # noqa: E402

sys.path.insert(0, HERE)
import baseline_model as bm  # noqa: E402
import store  # noqa: E402  (reads STORE_PATH, so it must come after load_dotenv)

FEATURES_PATH = os.environ.get(
    "FEATURES_PATH", os.path.expanduser("~/ArduinoApps/durhack-sensors/live/features.json"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
EDGE_EVERY_S = float(os.environ.get("EDGE_EVERY_S", "2"))
LEARN_SECONDS = 30
DURESS_AT, WATCH_AT = 0.60, 0.35

lock = threading.Lock()
cam = {"jpeg": None, "raw": None, "faces": 0, "others": 0, "far": 0, "ok": False, "fps": 0.0, "detector": None,
       "watching": 0, "dwell": 0.0, "over_shoulder": False, "user_facing": None}
recent_others = collections.deque(maxlen=6)   # smooth face-count flicker over ~0.6 s
yubikey = {"present": None, "checked": 0.0}
edge = {"result": None, "at": 0.0, "latency": None, "error": None, "calls": 0}
history = collections.deque(maxlen=240)       # 2 minutes at 2 Hz


# ------------------------------------------------------------------ camera
def _iou(a, b):
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter or 1)


YUNET_MODEL = os.path.join(HERE, "models", "face_detection_yunet_2023mar.onnx")
DETECT_SIZE = tuple(int(v) for v in os.environ.get("DETECT_SIZE", "640x480").split("x"))
NEAR_RATIO = float(os.environ.get("NEAR_RATIO", "0.4"))
SHOULDER_DWELL_S = float(os.environ.get("SHOULDER_DWELL_S", "3"))
SHOULDER_MEMORY_S = float(os.environ.get("SHOULDER_MEMORY_S", "20"))   # someone who watched in the last 20 s still counts


def _facing(f) -> bool:
    """True if a YuNet face (with landmarks) is turned towards the camera, i.e. towards the
    screen it sits on. Uses how far the nose is from the midpoint between the eyes."""
    x, y, w, h, rx, ry, lx, ly, nx, ny = (float(v) for v in f[:10])
    eye_dist = abs(lx - rx)
    if eye_dist < 0.2 * w:           # eyes bunched together: head turned well away
        return False
    return abs(nx - (rx + lx) / 2) / eye_dist < 0.35


def make_detector():
    """YuNet (OpenCV's neural face detector) if its model is present, else Haar cascades.

    YuNet finds turned, tilted and small background faces that Haar misses, and gives eye and
    nose positions, used to tell whether a face is looking at the screen. Returns (name, detect)
    where detect(bgr_frame_at_DETECT_SIZE) -> list of (x, y, w, h, facing); facing is None
    when unknown (Haar).
    """
    if os.path.exists(YUNET_MODEL):
        yunet = cv2.FaceDetectorYN.create(YUNET_MODEL, "", DETECT_SIZE, score_threshold=0.6,
                                          nms_threshold=0.3, top_k=20)

        def detect(img):
            _, faces = yunet.detect(img)
            return [] if faces is None else [tuple(int(v) for v in f[:4]) + (_facing(f),) for f in faces]
        return "YuNet", detect

    front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")

    def detect(img):
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        w = gray.shape[1]
        boxes = list(front.detectMultiScale(gray, 1.1, 5, minSize=(24, 24)))
        boxes += list(profile.detectMultiScale(gray, 1.1, 5, minSize=(24, 24)))
        for (x, y, bw, bh) in profile.detectMultiScale(cv2.flip(gray, 1), 1.1, 5, minSize=(24, 24)):
            boxes.append((w - x - bw, y, bw, bh))   # profile cascade only finds one side
        return [tuple(b) + (None,) for b in boxes]
    return "Haar (download the YuNet model for better detection)", detect


def camera_loop():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    name, detect = make_detector()
    with lock:
        cam["detector"] = name
    print("face detector:", name, DETECT_SIZE, flush=True)
    for _ in range(30):
        cap.read()
    last = time.time()
    shoulder_since = shoulder_seen = None   # someone close AND facing the screen, continuously
    shoulder_at = 0.0                       # last time someone was over the shoulder
    while True:
        ok, frame = cap.read()
        if not ok:
            with lock:
                cam["ok"] = False
            time.sleep(0.5)
            continue
        fh, fw = frame.shape[:2]
        small = cv2.resize(frame, DETECT_SIZE)
        sx, sy = fw / DETECT_SIZE[0], fh / DETECT_SIZE[1]
        uniq = []
        for b in sorted(detect(small), key=lambda b: b[2] * b[3], reverse=True):
            if all(_iou(b, u) < 0.3 for u in uniq):
                uniq.append(b)
        _, raw = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        # The largest face is the user. Another face is NEAR if it is at least NEAR_RATIO of the
        # user's face width (roughly within 2.5x the user's distance); distant faces are ignored.
        # A near face that is also turned towards the screen, continuously for SHOULDER_DWELL_S,
        # is "over the shoulder". Coworkers facing their own work and passers-by never are.
        now = time.time()
        user_w = uniq[0][2] if uniq else 0
        near = watching = 0
        for i, (x, y, w, h, facing) in enumerate(uniq):
            is_near = i > 0 and w >= NEAR_RATIO * user_w
            is_watching = is_near and facing is not False
            near += is_near
            watching += is_watching
        if watching:
            shoulder_since = shoulder_since or now
            shoulder_seen = now
        elif shoulder_seen is None or now - shoulder_seen > 1.0:   # 1 s grace for missed frames
            shoulder_since = shoulder_seen = None
        dwell = now - shoulder_since if shoulder_since else 0.0
        over_shoulder = dwell >= SHOULDER_DWELL_S
        if over_shoulder:
            shoulder_at = now

        for i, (x, y, w, h, facing) in enumerate(uniq):
            is_near = i > 0 and w >= NEAR_RATIO * user_w
            x, y, w, h = int(x * sx), int(y * sy), int(w * sx), int(h * sy)
            if i == 0:
                colour, label, strong = (80, 200, 80), "you", True
            elif is_near and facing is not False:
                colour = (60, 60, 230) if over_shoulder else (0, 165, 255)
                label, strong = ("over shoulder" if over_shoulder else f"watching {dwell:.0f}s"), True
            elif is_near:
                colour, label, strong = (160, 160, 160), "nearby, not watching", False
            else:
                colour, label, strong = (160, 160, 160), "far away", False
            cv2.rectangle(frame, (x, y), (x + w, y + h), colour, 3 if strong else 1)
            cv2.putText(frame, label, (x, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 if strong else 0.4, colour, 2 if strong else 1)
        _, ann = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        with lock:
            cam.update(jpeg=ann.tobytes(), raw=raw.tobytes(), faces=len(uniq),
                       others=near, far=max(0, len(uniq) - 1 - near), ok=True,
                       watching=watching, dwell=round(dwell, 1), over_shoulder=over_shoulder, shoulder_at=shoulder_at,
                       user_facing=uniq[0][4] if uniq else None,
                       fps=round(0.8 * cam["fps"] + 0.2 / max(1e-3, now - last), 1))
            recent_others.append(near)
        last = now


# ------------------------------------------------------------------ sensors + baseline
class Baseline:
    KEYS = {"humidity": 0.5, "temp_c": 0.2, "shake_rms": 0.01, "moisture": 5.0}  # key -> min std

    def __init__(self):
        self.reset()

    def reset(self):
        self.samples, self.started, self.stats = [], time.time(), None

    def add(self, f):
        if self.stats is None:
            self.samples.append(f)
            if time.time() - self.started >= LEARN_SECONDS and len(self.samples) >= 20:
                self.stats = {}
                for k, floor in self.KEYS.items():
                    v = [s[k] for s in self.samples if s.get(k) is not None]
                    if v:
                        m = sum(v) / len(v)
                        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
                        self.stats[k] = (m, max(sd, floor))

    def z(self, f, k):
        if not self.stats or k not in self.stats or f.get(k) is None:
            return None
        m, sd = self.stats[k]
        return round((f[k] - m) / sd, 2)

    def progress(self):
        return 1.0 if self.stats else min(1.0, (time.time() - self.started) / LEARN_SECONDS)


baseline = Baseline()

# A synthetic calm profile instead of a live 30 s hold: the same every time (seeded), and no palm
# hold needed after a restart. Humidity and temperature use tools/gen_generic_training.py's calm
# ranges; shake and moisture use this mouse's calm range in its own units (the generator's raw shake
# column is ~10x what this Movement board reads at rest, which would hide real shaking).
SYNTH_CALM = {"humidity": (45.0, 12.0), "temp_c": (33.0, 2.5), "shake_rms": (0.015, 0.015), "moisture": (0.0, 5.0)}


def synthetic_baseline(n: int = 600, seed: int = 1) -> dict:
    import random
    r = random.Random(seed)
    stats = {}
    for k, (m, sd) in SYNTH_CALM.items():
        v = [r.gauss(m, sd) for _ in range(n)]
        if k in ("shake_rms", "moisture"):
            v = [abs(x) for x in v]          # these can't go negative
        mean = sum(v) / n
        spread = (sum((x - mean) ** 2 for x in v) / n) ** 0.5
        stats[k] = (round(mean, 4), round(max(spread, Baseline.KEYS[k]), 4))
    return stats


def use_synthetic_baseline():
    baseline.reset()
    baseline.stats = synthetic_baseline()
    baseline.kind = "synthetic"


if os.environ.get("BASELINE_MODE", "synthetic") == "synthetic":
    use_synthetic_baseline()
recent_features = collections.deque(maxlen=10)   # ~2 s of readings, averaged


def read_features():
    try:
        with open(FEATURES_PATH) as f:
            d = json.load(f)
        return d if time.time() - d.get("t", 0) < 3 else None
    except (OSError, ValueError):
        return None


def smoothed():
    if not recent_features:
        return None
    out = dict(recent_features[-1])
    for k in Baseline.KEYS:
        v = [r[k] for r in recent_features if r.get(k) is not None]
        out[k] = round(sum(v) / len(v), 4) if v else None
    out["shake_rms"] = max((r.get("shake_rms") or 0) for r in recent_features)  # peaks matter
    if not out.get("touch"):
        out.update(humidity=None, temp_c=None, moisture=None)
    return out


# ------------------------------------------------------------------ YubiKey presence
def yubikey_loop():
    # list_descriptors() reads the device list without opening anything. CtapHidDevice.list_devices()
    # opened every /dev/hidraw* and never closed them: 1,000+ leaked handles after ~1h50, then
    # "Too many open files" and the dashboard stopped answering.
    from fido2.hid import list_descriptors
    while True:
        try:
            present = any(getattr(d, "vid", None) == 0x1050 for d in list_descriptors())
        except Exception:
            present = False
        with lock:
            yubikey.update(present=present, checked=time.time())
        time.sleep(3)


# ------------------------------------------------------------------ Edge Impulse (on the board)
def _load_model():
    """The enrolled user's Edge Impulse model, decrypted from their profile (key from the STM32)."""
    try:
        user = os.environ.get("YU_USER") or json.load(open(os.environ.get(
            "DEVICE_STATE", os.path.join(os.path.dirname(__file__), "..", "python", "device.json")))).get("user")
        from bridge import StmBridge
        from userprofile import Profile
        return edge_model.get_model(user, Profile.from_bridge(StmBridge()))
    except (Exception, SystemExit) as e:   # no device state, or the STM32 relay isn't up yet
        m = edge_model.EdgeModel(runner=None, path="")
        m.error = f"model not loaded: {e}"
        return m


def edge_loop():
    """The model is a tie-breaker: it is only asked while the body sensors are uncertain.
    It runs on the board; no frame or reading leaves it. With no model loaded, the camera and
    the body score decide alone."""
    last_call = 0.0
    model = _load_model()
    if not model.ready:
        with lock:
            edge.update(error=model.error or "no model loaded")
        print(f"[edge] {model.error}: deciding from the body sensors and camera only", flush=True)
    while True:
        time.sleep(0.25)
        with lock:
            state = dict(current_state)
            recent = list(recent_features)
        # Only during a transaction: everyday use (gaming, a busy day) is never judged.
        if not model.ready or state.get("mode") != "approval" or not state.get("uncertain"):
            continue
        if time.time() - last_call < EDGE_EVERY_S and last_call >= approval.get("start", 0):
            continue
        last_call = time.time()
        context = {"faces": state.get("faces"), "others_close": state.get("others"),
                   "sweat_z": state.get("sweat_z"), "move_z": state.get("move_z")}
        try:
            from bridge import StmBridge
            from userprofile import hour_z
            context.update(hour_z(StmBridge(), datetime.now().hour))   # the STM32's per-hour z-scores
        except (Exception, SystemExit):
            pass
        t = time.time()
        r = model.score(recent[-10:], context)
        with lock:
            edge["calls"] += 1
            if r is None:
                edge.update(error=model.error or "no usable answer from the model", latency=None)
            else:
                edge.update(result=r, at=time.time(), latency=round(time.time() - t, 3), error=None)


# ------------------------------------------------------------------ decision
# The body sensors decide first. Only in the uncertain band do the camera and the model get a say.
CLEAR_NORMAL_BELOW = float(os.environ.get("CLEAR_NORMAL_BELOW", "0.25"))
CLEAR_DURESS_FROM = float(os.environ.get("CLEAR_DURESS_FROM", "0.75"))


# The body score itself comes from baseline_model.assess (two baselines, exertion and fatigue rules).


def decide(body, c, g_score, others):
    """Returns (verdict, score, path, reasons). path is how the decision was reached."""
    if body is not None and body < CLEAR_NORMAL_BELOW:
        return "NORMAL", body, "sensors", []
    if body is not None and body >= CLEAR_DURESS_FROM:
        return "DURESS", body, "sensors", ["strong stress signals from the body sensors"]

    # Uncertain (or no baseline yet): ask the camera, then the model.
    reasons = ["body signals borderline" if body is not None else "no personal baseline yet"]
    base = body if body is not None else 0.4
    # Over the shoulder now, or at any point in the last SHOULDER_MEMORY_S (an attacker watches you
    # type the payment, then may step back as you confirm).
    shoulder = c["over_shoulder"] or time.time() - c.get("shoulder_at", 0.0) < SHOULDER_MEMORY_S
    g_alarm = g_score is not None and g_score >= DURESS_AT
    g_concern = g_score is not None and g_score >= WATCH_AT
    if shoulder:
        reasons.append("someone watching over your shoulder" if not c["over_shoulder"] else f"someone watching over your shoulder for {c['dwell']:.0f}s")
    if g_concern:
        reasons.append(f"the model sees possible coercion ({g_score:.2f})")
    if shoulder and g_concern:
        return "DURESS", max(0.8, base), "camera", reasons
    if shoulder or g_alarm:
        return "WATCH", max(0.5, base), "camera", reasons
    if g_concern:
        return "WATCH", max(0.4, base), "camera", reasons
    # Camera and model found nothing: the borderline reading is explained away.
    if others and not shoulder:
        reasons.append("people nearby, but nobody watching the screen")
    else:
        reasons.append("you're alone at the desk")
    return "NORMAL", min(base, 0.3), "camera", reasons


# ------------------------------------------------------------------ learning from the local store
learned = {}   # usual (this hour), recent (last 20 min + return/trend), tolerance, refreshed every 20 s


def learn_loop():
    """Pull this user's learned normal from the local store. Deterministic: plain aggregates and statistics."""
    from zoneinfo import ZoneInfo
    while True:
        if store.status.get("connected"):
            try:
                hour = datetime.now(ZoneInfo(store.TZ)).hour
                usual = store.usual_for_hour(hour)
                recent = bm.recent_from_rows(store.recent_rows(30), time.time())
                fa = store.false_alarms_near_hour(hour)
                with lock:
                    learned.update(usual=usual, recent=recent, false_alarms=fa, tolerance=bm.tolerance_for(fa),
                                   hour=hour, at=time.time(), error=None)
            except Exception as e:
                with lock:
                    learned["error"] = store._safe(e)
        time.sleep(20)


def _session_ref():
    if not baseline.stats:
        return None
    return {k: baseline.stats[k] for k in bm.KEYS if k in baseline.stats} or None


# ------------------------------------------------------------------ fusion
current_state = {}
_uncertain = {}   # {"since": t} while the body sensors are in the uncertain band


# The Thermo sits under the palm. Without a hand on the pad it reads the room, which poisons the
# baseline and the sweat score, so its readings only count while the pad is touched, and only after
# THERMO_SETTLE_S for the sensor to go from room air to palm (brief touch dropouts are bridged).
THERMO_SETTLE_S = float(os.environ.get("THERMO_SETTLE_S", "3"))
PALM_TEMP_MIN = float(os.environ.get("PALM_TEMP_MIN", "15"))
PALM_TEMP_MAX = float(os.environ.get("PALM_TEMP_MAX", "39"))
_palm = {"since": None, "last": 0.0}


# The Movement board sometimes reports one fixed value (shake_rms ~0.1224) for ~2.5 s with the hand
# still. Real shaking gives varying values, so a reading inside this narrow band is dropped as a glitch.
SHAKE_GLITCH = (float(os.environ.get("SHAKE_GLITCH_LO", "0.121")), float(os.environ.get("SHAKE_GLITCH_HI", "0.124")))


def palm_only(f: dict) -> dict:
    now = time.time()
    sh = f.get("shake_rms")
    if sh is not None and SHAKE_GLITCH[0] <= sh <= SHAKE_GLITCH[1]:
        f = {**f, "shake_rms": None}
    if f.get("touch"):
        _palm["last"] = now
        _palm["since"] = _palm["since"] or now
    elif now - _palm["last"] > 0.5:
        _palm["since"] = None
    if not f.get("touch") and now - _palm["last"] > 0.5:
        f = {**f, "moisture": None}            # sweat readings only count with a hand on the pad
    if _palm["since"] is None or now - _palm["since"] < THERMO_SETTLE_S:
        return {**f, "humidity": None, "temp_c": None}
    # The Thermo sometimes jumps in whole 10 degree steps (30 -> 80 C) with humidity jumping alongside.
    # No palm is outside this range, so drop the whole reading rather than learn or score a glitch.
    t = f.get("temp_c")
    if t is None or not (PALM_TEMP_MIN <= t <= PALM_TEMP_MAX):
        return {**f, "humidity": None, "temp_c": None}
    return f


def compute_state():
    f = read_features()
    if f:
        f = palm_only(f)
        recent_features.append(f)
        baseline.add(f)
    s = smoothed() if f else None
    with lock:
        others_conf = sorted(recent_others)[len(recent_others) // 2] if recent_others else 0  # median
        c = dict(cam)
        yk = yubikey["present"]
        g = dict(edge)

    with lock:
        L = dict(learned)
    # With the synthetic profile on, it is the ONLY reference: the stored "usual for this hour" and
    # "last 20 min" would otherwise take over once enough readings pile up, and those were learned
    # partly with the Thermo reading room air (humidity ~25% with a tiny spread, so a real palm read +45 sigma).
    synthetic = getattr(baseline, "kind", None) == "synthetic"
    usual_ref = None if synthetic else L.get("usual")
    recent_ref = None if synthetic else L.get("recent")
    # The moisture probe reads 0 until skin happens to touch it, then ~100+: contact, not sweat. Unless
    # SWEAT_USE_MOISTURE=1 it is shown and stored but left out of the score (sweat = palm humidity).
    scored = s if (not s or os.environ.get("SWEAT_USE_MOISTURE") == "1") else {**s, "moisture": None}
    a = bm.assess(scored, usual_ref, recent_ref, _session_ref(), L.get("tolerance", 1.0)) if s else None
    body = a["body"] if a else None
    sweat_z = a["groups"]["sweat"]["z"] if a and a["groups"].get("sweat") else None
    move_z = a["groups"]["movement"]["z"] if a and a["groups"].get("movement") else None
    signals = []
    for name, z in (("sweating more than normal", sweat_z), ("moving differently from normal", move_z)):
        if z is not None and z > 2:
            signals.append(f"{name} ({z:+.1f}σ)")
    explanations = a["explanations"] if a else []

    with lock:
        if approval["active"] and time.time() - approval["start"] > APPROVAL_MAX_S:
            approval["active"] = False          # abandoned window: drop it without a verdict
        mode = "approval" if approval["active"] else "background"
    uncertain = body is None or CLEAR_NORMAL_BELOW <= body < CLEAR_DURESS_FROM
    # The model's answer only counts if it was given during this uncertain spell.
    if uncertain and "since" not in _uncertain:
        _uncertain["since"] = time.time()
    if not uncertain:
        _uncertain.clear()
    g_fresh = (mode == "approval" and uncertain and g["result"] is not None
               and g["at"] >= max(_uncertain.get("since", 0), approval["start"])
               and time.time() - g["at"] < 3 * EDGE_EVERY_S + 10)
    g_score = g["result"]["duress_score"] if g_fresh else None

    verdict, score, path, reasons = decide(body, c, g_score, others_conf)
    signals = signals + [r for r in reasons if r not in signals]

    if mode == "approval":
        with lock:
            approval["samples"].append({
                "verdict": verdict, "score": round(score, 2), "decided_by": path, "signals": list(signals),
                "explanation": "; ".join(explanations) or None, "body_score": body,
                "reasoning": (g["result"] or {}).get("reasoning") if g_fresh else None})

    st = {
        "t": time.time(), "verdict": verdict, "score": round(score, 2), "mode": mode,
        "approval": {"active": mode == "approval", "elapsed": round(time.time() - approval["start"], 1) if mode == "approval" else None,
                     "label": approval["label"] if mode == "approval" else None, "last": approval["last"]},
        "local_score": round(body, 2) if body is not None else None, "body_score": body,
        "decided_by": path, "uncertain": uncertain, "signals": signals if verdict != "NORMAL" or path == "camera" else [],
        "camera_ok": c["ok"], "fps": c["fps"], "faces": c["faces"], "others": others_conf,
        "detector": c["detector"], "far": c["far"], "dwell": c["dwell"], "over_shoulder": c["over_shoulder"],
        "watching": c["watching"],
        "sensors_ok": f is not None, "features": s,
        "sweat_z": sweat_z, "move_z": move_z, "touch": (s or {}).get("touch"),
        "baseline_ready": baseline.stats is not None or bool(a and a["baseline_kind"]),
        "baseline_progress": round(baseline.progress(), 2),
        "baseline": baseline.stats,
        "assessment": {"kind": a["baseline_kind"] if a else None, "groups": a["groups"] if a else {},
                       "tolerance": a["tolerance"] if a else 1.0, "returned_s": a["returned_s"] if a else None,
                       "explanations": explanations,
                       "usual_n": sum(((L.get("usual") or {}).get(k) or (0, 0, 0))[2] for k in bm.KEYS),
                       "recent_n": (L.get("recent") or {}).get("n", 0), "hour": L.get("hour"),
                       "false_alarms": L.get("false_alarms", 0), "learn_error": L.get("error")},
        "yubikey": yk,
        "edge": {"score": g_score, "fresh": g_fresh, "needed": uncertain and mode == "approval", "latency": g["latency"],
                   "error": g["error"] if uncertain and mode == "approval" else None,
                   "calls": g["calls"], "model": os.environ.get("PROFILE_DIR"),
                   "signals": (g["result"] or {}).get("signals") if g_fresh else None,
                   "reasoning": (g["result"] or {}).get("reasoning") if g_fresh else None},
    }
    with lock:
        current_state.clear()
        current_state.update(st)
        history.append({"t": st["t"], "score": st["score"], "local": st["local_score"], "edge": g_score,
                        "uncertain": uncertain})
    store_reading(st, s)


# ------------------------------------------------------------------ Local store
_last_store = 0.0


def store_reading(st, s):
    """One reading per second into the local store."""
    global _last_store
    if st["t"] - _last_store >= 1.0:
        _last_store = st["t"]
        f = s or {}
        hand = bool(f.get("touch"))
        if not hand:   # sweat (humidity, temperature, moisture) is only stored with a hand on the pad
            f = {**f, "humidity": None, "temp_c": None, "moisture": None}
        store.record({
            "time": datetime.fromtimestamp(st["t"], timezone.utc),
            "device": store.DEVICE, "verdict": st["verdict"], "score": st["score"],
            "local_score": st["local_score"], "edge_score": st["edge"]["score"],
            "faces": st["faces"], "close_people": st["others"], "far_people": st["far"],
            "humidity": f.get("humidity"), "temp_c": f.get("temp_c"), "shake_rms": f.get("shake_rms"),
            "moisture": f.get("moisture"), "touch": bool(f.get("touch")) if f else None,
            "sweat_z": st["sweat_z"] if hand else None, "move_z": st["move_z"], "yubikey": st["yubikey"],
            "edge_latency": st["edge"]["latency"] if st["edge"]["fresh"] else None,
            "decided_by": st["decided_by"],
            # Enough to recompute this verdict: which baseline, the z-scores and each signal's state.
            "body_score": st["body_score"],
            "explanation": "; ".join(st["assessment"]["explanations"]) or None,
            "baseline": json.dumps({k: st["assessment"][k] for k in ("kind", "tolerance", "returned_s", "groups")}),
            "mode": st["mode"]})
    # Incidents are no longer opened from everyday readings: only a transaction can raise one
    # (see finish_approval). Gaming, exercise or a stressful day are learned from, never flagged.


# ------------------------------------------------------------------ transactions
# Only a transaction is judged. Everyday readings feed the learned baseline and the live view,
# but nothing is raised from them and no model is run.
APPROVAL_MAX_S = 20
approval = {"active": False, "start": 0.0, "label": None, "samples": [], "last": None}
_RANK = {"NORMAL": 0, "WATCH": 1, "DURESS": 2}
OUTCOME = {"NORMAL": "Approved", "WATCH": "Second approver needed", "DURESS": "Decoy sent, team alerted"}


def start_approval(label: str | None = None) -> float:
    with lock:
        approval.update(active=True, start=time.time(), label=label, samples=[])
        return approval["start"]


def finish_approval() -> dict | None:
    """The transaction's verdict: the most serious state seen during its window."""
    with lock:
        if not approval["active"]:
            return approval["last"]
        samples, start, label = list(approval["samples"]), approval["start"], approval["label"]
        approval["active"] = False
    if not samples:
        result = {"verdict": "WATCH", "score": 0.5, "decided_by": "none", "signals": ["no readings during the transaction"],
                  "reasoning": None, "explanation": None, "body_score": None}
    else:
        worst = max(samples, key=lambda x: (_RANK[x["verdict"]], x["score"]))
        reasoning = next((x["reasoning"] for x in reversed(samples) if x["reasoning"]), None)
        result = {k: worst[k] for k in ("verdict", "score", "decided_by", "signals", "explanation", "body_score")}
        result["reasoning"] = reasoning
    result.update(t=start, label=label, seconds=round(time.time() - start, 1), outcome=OUTCOME[result["verdict"]],
                  duress_score=result["score"])
    with lock:
        approval["last"] = result
    store.record_approval(start, label, result)
    if result["verdict"] != "NORMAL":
        store.incident_open(start, result["verdict"], result["score"], result["signals"], result["reasoning"])
        store.incident_update(start, result["verdict"], result["score"], result["signals"], result["reasoning"], ended=True)
    return result


def fusion_loop():
    while True:
        try:
            compute_state()
        except Exception as e:  # keep the dashboard alive whatever happens
            print("fusion error:", type(e).__name__, e, flush=True)
        time.sleep(0.5)


# ------------------------------------------------------------------ web
app = FastAPI()


@app.get("/")
def index():
    with open(os.path.join(HERE, "index.html")) as f:
        return HTMLResponse(f.read())


@app.get("/state")
def state():
    with lock:
        return JSONResponse({**current_state, "history": list(history)})


@app.post("/calibrate")
def calibrate(mode: str | None = None):
    """No mode: learn live from the next 30 s with a hand on the pad. mode=synthetic: the synthetic calm profile."""
    if mode == "synthetic":
        use_synthetic_baseline()
        return {"ok": True, "baseline": "synthetic", "stats": baseline.stats}
    baseline.reset()
    baseline.kind = "live"
    return {"ok": True, "baseline": "live"}


def _store(fn, *args):
    try:
        return JSONResponse(fn(*args))
    except Exception as e:
        return JSONResponse({"error": store._safe(e)}, status_code=502)


@app.get("/api/store")
def api_store():
    out = dict(store.status)
    if store.status["connected"]:
        try:
            out["stats"] = store.stats()
        except Exception as e:
            out["stats_error"] = store._safe(e)
    return JSONResponse(out)


@app.get("/api/history")
def api_history(range: str = "15m"):
    return _store(store.history, range)


@app.get("/api/normal")
def api_normal():
    return _store(store.normal_by_hour)


@app.get("/api/incidents")
def api_incidents():
    return _store(store.incidents)


@app.post("/api/approval/start")
def api_approval_start(label: str | None = None):
    return {"started": start_approval(label)}


@app.post("/api/approval/finish")
def api_approval_finish():
    return JSONResponse(finish_approval() or {"error": "no transaction in progress"})


@app.post("/api/assess")
def api_assess(label: str | None = None, seconds: float = 3.0):
    """One-shot transaction check for app/python/main.py: opens a window, gathers `seconds` of
    readings (plus the on-board model if the sensors are unsure, up to 12 s), and returns the verdict in
    edge_model's format (duress_score, signals, reasoning) plus verdict/decided_by/outcome."""
    return JSONResponse(_assess(label, seconds))


def _assess(label, seconds):
    start_approval(label)
    time.sleep(max(1.0, min(seconds, 10.0)))
    deadline = time.time() + 12
    while time.time() < deadline:   # sensors unsure: wait for the model to break the tie
        with lock:
            st = dict(current_state)
        if not st.get("uncertain") or st.get("edge", {}).get("fresh") or st.get("edge", {}).get("error"):
            break
        time.sleep(0.25)
    return finish_approval()


# ------------------------------------------------------------------ payment page (the customer's side, demo)
# Anything but a clean NORMAL gets a decoy receipt. It looks exactly like the real one: same page,
# same JSON shape, same fields. The only difference is one word in the headline ("Payment sent <word>").
# The real receipt uses the user's word (YUDUINO_TELL in .env); a decoy uses YUDUINO_DECOY, or by default
# the same word with its first letter's case flipped (successfully -> Successfully). An attacker
# sees "Payment sent" either way; only the user knows which spelling is theirs.
def _decoy_word(tell: str) -> str:
    d = os.environ.get("YUDUINO_DECOY", "").strip()
    if d and d != tell:
        return d
    flipped = tell[:1].swapcase() + tell[1:]
    return flipped if flipped != tell else tell + "."


class Payment(BaseModel):
    to: str = ""
    amount: str = ""
    reference: str = ""


@app.get("/pay")
def pay_page():
    with open(os.path.join(HERE, "pay.html")) as f:
        return HTMLResponse(f.read())


CLICK_WAIT_S = float(os.environ.get("CLICK_WAIT_S", "5"))


def _wait_for_click(digest_hex: str):
    """Arm the STM32 with this payment's digest. It accepts only after a real button-C press with the
    palm on the pad in the last 1.5 s, decided in its trusted core; Linux never sees the press itself.
    Returns the bridge (armed, must be sealed) or None if no such click came in time."""
    from bridge import StmBridge
    b = StmBridge()
    deadline = time.time() + CLICK_WAIT_S
    while time.time() < deadline:
        try:
            if b.call("arm_approval", digest_hex) == "1":
                return b
        except (Exception, SystemExit):
            pass
        time.sleep(0.1)
    return None


@app.post("/api/pay")
def api_pay(p: Payment):
    """Silent: the page only says "Processing payment". The owner presses button C (to anyone
    watching, an ordinary mouse click) with a palm on the pad; then the board checks them for a few
    seconds. No press within CLICK_WAIT_S means the payment silently doesn't go through: decoy."""
    import hashlib
    receipt = {"to": p.to[:60], "amount": p.amount[:20], "reference": p.reference[:40],
               "id": "TXN-" + os.urandom(4).hex().upper()}
    digest = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    armed = _wait_for_click(digest)
    if armed is None:
        r = {"t": time.time(), "verdict": "NO_CLICK", "score": 1.0, "decided_by": "mouse",
             "signals": ["no button-C press with a hand on the mouse"], "explanation": None,
             "body_score": None, "seconds": CLICK_WAIT_S}
    else:
        r = {}
        try:
            r = _assess("payment", 3) or {}
        finally:
            score = r.get("score")
            try:   # always end the STM32's session, or it stays armed and refuses the next click
                armed.call("seal_approval", str(round(score * 100) if score is not None else -1), "0")
            except (Exception, SystemExit):
                pass
    genuine = r.get("verdict") == "NORMAL"
    tell = os.environ.get("YUDUINO_TELL", "").strip()
    word = (tell if genuine else _decoy_word(tell)) if tell else None
    if not genuine:   # the dashboard (security team's view) records what really happened
        with lock:
            if approval.get("last") is r:
                r["outcome"] = "Decoy receipt shown, team alerted"
    receipt.update(time=time.time(), word=word)
    with lock:   # for the judges' page: what the screen showed vs what really happened (never the word)
        payments.append({"t": r.get("t", receipt["time"]), "to": receipt["to"], "amount": receipt["amount"],
                         "id": receipt["id"], "shown": "real" if genuine else "decoy",
                         **{k: r.get(k) for k in ("verdict", "score", "decided_by", "signals", "explanation", "body_score", "seconds")}})
    return receipt


payments = collections.deque(maxlen=20)


@app.get("/api/payments")
def api_payments():
    with lock:
        return JSONResponse(list(payments)[::-1])


@app.get("/demo")
def demo_page():
    with open(os.path.join(HERE, "demo.html")) as f:
        return HTMLResponse(f.read())


@app.post("/api/incidents/label")
def api_label(t: float, label: str):
    """Mark an incident as a false alarm (widens tolerance at that time of day, capped) or confirmed.
    Demo only: in a real deployment this would need compliance/security sign-in."""
    return _store(lambda: {"ok": store.label_incident(t, None if label == "clear" else label)})


@app.get("/frame.jpg")
def frame():
    """Latest annotated frame. The page polls this, so it recovers by itself after a restart
    (a broken MJPEG <img> stream stays blank until the page is reloaded)."""
    with lock:
        jpg = cam["jpeg"]
    if not jpg:
        return Response(status_code=503)
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/snapshot")
def snapshot():
    """The latest UNannotated frame, for app/python/camera.py: the dashboard owns the camera, so
    the approval flow asks it for a frame instead of opening the device a second time."""
    with lock:
        jpg, faces = cam["raw"], cam["faces"]
    if not jpg:
        return Response(status_code=503)
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Faces": str(faces)})


@app.get("/video.mjpg")
def video():
    def frames():
        while True:
            with lock:
                jpg = cam["jpeg"]
            if jpg:
                yield b"--f\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            time.sleep(0.12)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=f")


if __name__ == "__main__":
    print("Local store:", store.PATH, flush=True)
    for fn in (camera_loop, yubikey_loop, edge_loop, fusion_loop, store.writer_loop, learn_loop):
        threading.Thread(target=fn, daemon=True).start()
    print(f"Dashboard on http://0.0.0.0:{PORT}  (sensors from {FEATURES_PATH})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
