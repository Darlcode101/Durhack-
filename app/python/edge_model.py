"""The on-device duress model: an Edge Impulse model running on the UNO Q's Linux side.

Nothing leaves the board: no cloud call, no frame sent anywhere. At the moment of a transaction
(and only then) the window of readings taken right after the click becomes one flat feature vector,
the model returns class probabilities, and the probability of the duress class is the duress score.
The STM32 still takes that score (0..100), applies the veto and the decision rule, and tags it.

    The model is unique to its user, trained only on that user's own normal data, and stored
    encrypted (AES-256-GCM, key derived by the STM32; see userprofile.py). It is decrypted into RAM
    only to run. Import one with:  python3 main.py import-model <user> <file.eim>
    EI_DURESS_LABEL   if the model is a classifier, the class that means duress (default "duress")
    EI_ANOMALY_LIMIT  if it is an anomaly model, the anomaly score that counts as "unusual"
                      (default 1.0): the duress score is 0.5 at the limit and 1.0 at twice the limit

Reply format (what approve.py and the dashboard expect):
    {"duress_score": 0.0..1.0, "signals": [...], "reasoning": "...", "source": "edge_impulse"}
or None when there is no usable verdict. None fails closed to duress.

Fallback order when there is no model file: the dashboard's own learned body score (see
main.model_fn), then None (duress). Fail closed, never open.
"""
from __future__ import annotations

import os

# The input vector, in this order. The Edge Impulse project's raw-data input block must use the
# same names in the same order (one row per approval window).
FEATURE_NAMES = (
    "temp_c_mean", "humidity_mean", "humidity_delta", "shake_rms_mean", "shake_rms_max",
    "moisture_mean", "moisture_delta", "grip_fraction", "click_hold_ms",
    "faces", "others_close", "sweat_z", "move_z",
    "hour_z_humidity", "hour_z_moisture", "hour_z_shake", "hour_z_temp",   # from the STM32's per-hour baseline
)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def feature_vector(window: list[dict], context: dict | None = None) -> list[float]:
    """Readings sampled right after the click (the STM32 `get_features` dicts) plus optional context
    from the camera and the personal baseline (faces, others_close, sweat_z, move_z; missing = 0)."""
    ctx = context or {}

    def col(k):
        return [float(f[k]) for f in window if isinstance(f.get(k), (int, float))]

    hum, moist, shake, temp = col("humidity"), col("moisture"), col("shake_rms"), col("temp_c")
    grips = [1.0 if f.get("grip") or f.get("touch") else 0.0 for f in window]

    def num(k):
        v = ctx.get(k)
        return float(v) if isinstance(v, (int, float)) else 0.0

    return [_mean(temp), _mean(hum), (hum[-1] - hum[0]) if len(hum) > 1 else 0.0,
            _mean(shake), max(shake) if shake else 0.0,
            _mean(moist), (moist[-1] - moist[0]) if len(moist) > 1 else 0.0, _mean(grips), _mean(col("hold_ms")),
            num("faces"), num("others_close"), num("sweat_z"), num("move_z"),
            num("hour_z_humidity"), num("hour_z_moisture"), num("hour_z_shake"), num("hour_z_temp")]


class EdgeModel:
    """A loaded Edge Impulse model. `runner` is injectable so tests need no model file."""

    def __init__(self, path: str | None = None, runner=None, label: str | None = None, user: str | None = None,
                 profile=None, limit: float | None = None):
        self.label = label or os.environ.get("EI_DURESS_LABEL", "duress")
        self.limit = limit or float(os.environ.get("EI_ANOMALY_LIMIT", "1.0"))
        self.error: str | None = None
        self.runner = runner
        if runner is None:
            tmp = None
            try:
                if path is None and profile is not None and user:
                    path = tmp = profile.open_model(user)       # decrypted into RAM, deleted below
                if not path:
                    self.error = "no model for this user: import one (main.py import-model <user> <file.eim>)"
                elif not os.path.exists(path):
                    self.error = f"model file not found: {path}"
                else:
                    from edge_impulse_linux.runner import ImpulseRunner
                    self.runner = ImpulseRunner(path)
                    self.runner.init()
            except Exception as e:  # missing package, wrong architecture, bad file, bad key
                self.runner, self.error = None, f"model not loadable: {e}"
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)   # the running model keeps working; no plaintext stays on disk
                    except OSError:
                        pass

    @property
    def ready(self) -> bool:
        return self.runner is not None

    def score(self, window: list[dict], context: dict | None = None) -> dict | None:
        if not self.ready or not window:
            return None
        try:
            res = self.runner.classify(feature_vector(window, context))["result"]
            if "classification" in res and self.label in res["classification"]:
                probs = res["classification"]
                p = float(probs[self.label])
                top = max(probs, key=probs.get)
                note = f"model: {top} ({probs[top]:.2f})"
            elif "anomaly" in res:
                a = float(res["anomaly"])
                p = a / (2 * self.limit)           # 0.5 at the limit, 1.0 at twice the limit
                p, note = min(p, 1.0), f"anomaly score {a:.2f} (limit {self.limit:g})"
            else:
                raise KeyError("neither a duress class nor an anomaly score in the model output")
        except Exception as e:  # never let a model fault look like calm
            self.error = f"classify failed: {e}"
            return None
        if not 0.0 <= p <= 1.0 or p != p:
            return None
        return {"duress_score": p, "signals": [note],
                "reasoning": "Edge Impulse model on the board", "source": "edge_impulse"}


_models: dict = {}


def get_model(user: str | None = None, profile=None) -> EdgeModel:
    """One model per person, loaded once (decrypted from their profile)."""
    if user not in _models:
        _models[user] = EdgeModel(user=user, profile=profile)
    return _models[user]


def edge_score(window: list[dict], context: dict | None = None, user: str | None = None, profile=None) -> dict | None:
    """Score one approval window with that person's on-device model. None = no usable verdict (fails closed)."""
    return get_model(user, profile).score(window, context)
