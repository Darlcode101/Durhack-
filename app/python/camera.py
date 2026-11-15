"""USB camera capture + cheap on-board face count (Haar cascade, runs fine in 2 GB RAM).

Frames are kept in memory only — never written to disk (privacy).
"""
import os

import cv2

_cap = None
_faces = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def _camera():
    global _cap
    if _cap is None:
        _cap = cv2.VideoCapture(0)  # VERIFY the index once the camera is on the USB-C hub
        _cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        _cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        for _ in range(30):  # first frames are dark until auto-exposure settles (~1 s)
            _cap.read()
    return _cap


def _from_dashboard() -> tuple[bytes | None, int]:
    """The live dashboard holds the camera (a USB camera can't be opened twice), so ask it."""
    try:
        import requests
        r = requests.get(os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8080") + "/api/snapshot", timeout=1.5)
        if r.status_code == 200 and r.content:
            return r.content, int(r.headers.get("X-Faces", "0"))
    except Exception:
        pass
    return None, 0


def grab() -> tuple[bytes | None, int]:
    """Returns (jpeg_bytes, face_count). jpeg is None if the camera failed."""
    jpg, faces = _from_dashboard()
    if jpg:
        return jpg, faces
    ok, frame = _camera().read()
    if not ok:
        return None, 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _faces.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return (jpg.tobytes() if ok else None), len(faces)
