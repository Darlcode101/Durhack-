"""YuDuino live duress monitor (test dashboard). Runs on the UNO Q's Linux side, in the venv.

    ~/durhack-venv/bin/python app/dashboard/server.py      then open http://<board-ip>:8080

Inputs, all passive (no buttons, no user input):
  * camera: is anyone besides the user in view? (largest face = user, any other face = someone else)
  * sensors (STM32 -> App Lab relay -> live/features.json): sweat (moisture + palm humidity),
    movement (Modulino Movement shake), grip (touch), palm temperature
  * YubiKey: plugged in or not (presence only; no touch is requested)
  * Gemini: every few seconds, one frame + a summary of the above -> duress score with reasons

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

from fusion_gemini import gemini_score  # noqa: E402

sys.path.insert(0, HERE)
import tiger  # noqa: E402  (reads TIGER_DATABASE_URL, so it must come after load_dotenv)

FEATURES_PATH = os.environ.get(
    "FEATURES_PATH", os.path.expanduser("~/ArduinoApps/durhack-sensors/live/features.json"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
GEMINI_EVERY_S = float(os.environ.get("GEMINI_EVERY_S", "5"))
LEARN_SECONDS = 30
DURESS_AT, WATCH_AT = 0.60, 0.35

lock = threading.Lock()
cam = {"jpeg": None, "raw": None, "faces": 0, "others": 0, "far": 0, "ok": False, "fps": 0.0, "detector": None}
recent_others = collections.deque(maxlen=6)   # smooth face-count flicker over ~0.6 s
yubikey = {"present": None, "checked": 0.0}
gemini = {"result": None, "at": 0.0, "latency": None, "error": None, "calls": 0}
history = collections.deque(maxlen=240)       # 2 minutes at 2 Hz


# ------------------------------------------------------------------ camera
def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter or 1)


YUNET_MODEL = os.path.join(HERE, "models", "face_detection_yunet_2023mar.onnx")
DETECT_SIZE = tuple(int(v) for v in os.environ.get("DETECT_SIZE", "640x480").split("x"))
NEAR_RATIO = float(os.environ.get("NEAR_RATIO", "0.4"))


def make_detector():
    """YuNet (OpenCV's neural face detector) if its model is present, else Haar cascades.

    YuNet finds turned, tilted and small background faces that Haar misses. Returns
    (name, detect) where detect(bgr_frame_at_DETECT_SIZE) -> list of (x, y, w, h).
    """
    if os.path.exists(YUNET_MODEL):
        yunet = cv2.FaceDetectorYN.create(YUNET_MODEL, "", DETECT_SIZE, score_threshold=0.6,
                                          nms_threshold=0.3, top_k=20)

        def detect(img):
            _, faces = yunet.detect(img)
            return [] if faces is None else [tuple(int(v) for v in f[:4]) for f in faces]
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
        return boxes
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
        # The largest face is the user. Another face only counts if it is NEAR: at least
        # NEAR_RATIO of the user's face width (roughly within 2.5x the user's distance).
        # Distant faces (people across the room) are boxed grey and ignored.
        user_w = uniq[0][2] if uniq else 0
        near = 0
        for i, (x, y, w, h) in enumerate(uniq):
            is_near = i > 0 and w >= NEAR_RATIO * user_w
            near += is_near
            x, y, w, h = int(x * sx), int(y * sy), int(w * sx), int(h * sy)
            if i == 0:
                colour, label = (80, 200, 80), "you"
            elif is_near:
                colour, label = (60, 60, 230), "someone close"
            else:
                colour, label = (160, 160, 160), "far away"
            cv2.rectangle(frame, (x, y), (x + w, y + h), colour, 3 if i == 0 or is_near else 1)
            cv2.putText(frame, label, (x, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 if i == 0 or is_near else 0.4, colour, 2 if i == 0 or is_near else 1)
        _, ann = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        now = time.time()
        with lock:
            cam.update(jpeg=ann.tobytes(), raw=raw.tobytes(), faces=len(uniq),
                       others=near, far=max(0, len(uniq) - 1 - near), ok=True,
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
    return out


# ------------------------------------------------------------------ YubiKey presence
def yubikey_loop():
    from fido2.hid import CtapHidDevice
    while True:
        try:
            present = any(getattr(d.descriptor, "vid", None) == 0x1050 for d in CtapHidDevice.list_devices())
        except Exception:
            present = False
        with lock:
            yubikey.update(present=present, checked=time.time())
        time.sleep(3)


# ------------------------------------------------------------------ Gemini
def gemini_loop():
    while True:
        time.sleep(GEMINI_EVERY_S)
        with lock:
            raw = cam["raw"]
            state = dict(current_state)
        if not raw or not os.environ.get("GEMINI_API_KEY"):
            continue
        summary = {
            "people_in_view": state.get("faces"),
            "other_people_close_to_user": state.get("others"),
            "distant_people_in_background": state.get("far"),
            "sweat_z_vs_own_normal": state.get("sweat_z"),
            "movement_z_vs_own_normal": state.get("move_z"),
            "grip_held": state.get("touch"),
            "yubikey_connected": state.get("yubikey"),
            "baseline_ready": state.get("baseline_ready"),
            "note": "z = standard deviations above this user's own calm baseline; null = not available",
        }
        t = time.time()
        r = gemini_score(raw, summary, timeout_s=10)
        with lock:
            gemini["calls"] += 1
            if r is None:
                gemini.update(error="no usable answer (timeout, quota or bad reply)", latency=None)
            else:
                gemini.update(result=r, at=time.time(), latency=round(time.time() - t, 1), error=None)
        if r is None:
            time.sleep(10)   # back off on quota / outage


# ------------------------------------------------------------------ fusion
current_state = {}


def compute_state():
    f = read_features()
    if f:
        recent_features.append(f)
        baseline.add(f)
    s = smoothed() if f else None
    with lock:
        others_conf = sorted(recent_others)[len(recent_others) // 2] if recent_others else 0  # median
        c = dict(cam)
        yk = yubikey["present"]
        g = dict(gemini)

    signals, local = [], 0.0
    if others_conf >= 1:
        local += 0.6
        signals.append(f"{others_conf} person close behind you" if others_conf == 1 else f"{others_conf} people close behind you")

    sweat_z = move_z = None
    if s and baseline.stats:
        zs = [z for z in (baseline.z(s, "humidity"), baseline.z(s, "moisture")) if z is not None]
        sweat_z = max(zs) if zs else None
        move_z = baseline.z(s, "shake_rms")
        for name, z in (("sweating more than normal", sweat_z), ("moving differently from normal", move_z)):
            if z is not None and z > 3:
                local += 0.25
                signals.append(f"{name} ({z:+.1f}σ)")
            elif z is not None and z > 2:
                local += 0.12
                signals.append(f"slightly {name} ({z:+.1f}σ)")
    local = min(1.0, local)

    g_fresh = g["result"] is not None and time.time() - g["at"] < 3 * GEMINI_EVERY_S + 10
    g_score = g["result"]["duress_score"] if g_fresh else None
    score = max(local, g_score or 0.0)
    if g_fresh and g_score >= WATCH_AT:
        signals.append(f"Gemini: {g_score:.2f}")
    verdict = "DURESS" if score >= DURESS_AT else "WATCH" if score >= WATCH_AT else "NORMAL"

    st = {
        "t": time.time(), "verdict": verdict, "score": round(score, 2), "local_score": round(local, 2),
        "signals": signals,
        "camera_ok": c["ok"], "fps": c["fps"], "faces": c["faces"], "others": others_conf,
        "detector": c["detector"], "far": c["far"],
        "sensors_ok": f is not None, "features": s,
        "sweat_z": sweat_z, "move_z": move_z, "touch": (s or {}).get("touch"),
        "baseline_ready": baseline.stats is not None, "baseline_progress": round(baseline.progress(), 2),
        "baseline": baseline.stats,
        "yubikey": yk,
        "gemini": {"score": g_score, "fresh": g_fresh, "latency": g["latency"], "error": g["error"],
                   "calls": g["calls"], "model": os.environ.get("GEMINI_MODEL"),
                   "signals": (g["result"] or {}).get("signals") if g_fresh else None,
                   "reasoning": (g["result"] or {}).get("reasoning") if g_fresh else None},
    }
    with lock:
        current_state.clear()
        current_state.update(st)
        history.append({"t": st["t"], "score": st["score"], "local": st["local_score"], "gemini": g_score})
    store(st, s)


# ------------------------------------------------------------------ Tiger Data
incident = {"start": None, "peak": 0.0, "verdict": None}
_last_store = 0.0


def store(st, s):
    """One reading per second into the hypertable; open/update/close incidents on verdict changes."""
    global _last_store
    if not tiger.URL:
        return
    if st["t"] - _last_store >= 1.0:
        _last_store = st["t"]
        f = s or {}
        tiger.record({
            "time": datetime.fromtimestamp(st["t"], timezone.utc),
            "device": tiger.DEVICE, "verdict": st["verdict"], "score": st["score"],
            "local_score": st["local_score"], "gemini_score": st["gemini"]["score"],
            "faces": st["faces"], "close_people": st["others"], "far_people": st["far"],
            "humidity": f.get("humidity"), "temp_c": f.get("temp_c"), "shake_rms": f.get("shake_rms"),
            "moisture": f.get("moisture"), "touch": bool(f.get("touch")) if f else None,
            "sweat_z": st["sweat_z"], "move_z": st["move_z"], "yubikey": st["yubikey"],
            "gemini_latency": st["gemini"]["latency"]})
    reason = st["gemini"]["reasoning"]
    if st["verdict"] != "NORMAL":
        if incident["start"] is None:
            incident.update(start=st["t"], peak=st["score"], verdict=st["verdict"])
            tiger.incident_open(st["t"], st["verdict"], st["score"], st["signals"], reason)
        elif st["score"] > incident["peak"] or (st["verdict"] == "DURESS" and incident["verdict"] != "DURESS"):
            incident.update(peak=max(incident["peak"], st["score"]),
                            verdict="DURESS" if st["verdict"] == "DURESS" else incident["verdict"])
            tiger.incident_update(incident["start"], st["verdict"], st["score"], st["signals"], reason, ended=False)
    elif incident["start"] is not None:
        tiger.incident_update(incident["start"], "NORMAL", 0.0, [], None, ended=True)
        incident.update(start=None, peak=0.0, verdict=None)


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
def calibrate():
    baseline.reset()
    return {"ok": True}


def _tiger(fn, *args):
    if not tiger.URL:
        return JSONResponse({"error": "Tiger not configured (set TIGER_DATABASE_URL in .env)"}, status_code=503)
    try:
        return JSONResponse(fn(*args))
    except Exception as e:
        return JSONResponse({"error": tiger._safe(e)}, status_code=502)


@app.get("/api/tiger")
def api_tiger():
    out = dict(tiger.status)
    if tiger.URL and tiger.status["connected"]:
        try:
            out["stats"] = tiger.stats()
        except Exception as e:
            out["stats_error"] = tiger._safe(e)
    return JSONResponse(out)


@app.get("/api/history")
def api_history(range: str = "15m"):
    return _tiger(tiger.history, range)


@app.get("/api/normal")
def api_normal():
    return _tiger(tiger.normal_by_hour)


@app.get("/api/incidents")
def api_incidents():
    return _tiger(tiger.incidents)


@app.get("/frame.jpg")
def frame():
    """Latest annotated frame. The page polls this, so it recovers by itself after a restart
    (a broken MJPEG <img> stream stays blank until the page is reloaded)."""
    with lock:
        jpg = cam["jpeg"]
    if not jpg:
        return Response(status_code=503)
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
    print("Tiger Data:", "configured" if tiger.URL else "not configured (live view only)", flush=True)
    for fn in (camera_loop, yubikey_loop, gemini_loop, fusion_loop, tiger.writer_loop):
        threading.Thread(target=fn, daemon=True).start()
    print(f"Dashboard on http://0.0.0.0:{PORT}  (sensors from {FEATURES_PATH})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
