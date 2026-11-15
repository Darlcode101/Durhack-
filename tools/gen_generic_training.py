"""Generate the GENERIC Edge Impulse training set: synthetic calm rows, no real person's data.

    python3 tools/gen_generic_training.py out.csv [rows]      (default 2000 rows)

Upload the CSV to Edge Studio and train an anomaly detection block on it. Each mouse personalises the
generic model on the device: its per-hour z-score features (hour_z_*, sweat_z, move_z) are the user's
own reading against their own per-hour mean and spread, so the same model means "unusual for this
person". The raw columns are drawn broadly so no single person's values define "normal".
Columns are edge_model.FEATURE_NAMES, in order.
"""
import csv
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "python"))
import edge_model


def row(r):
    g = r.gauss
    return [g(33, 2.5), g(45, 12), g(0, 1.5), abs(g(0.12, 0.08)), abs(g(0.25, 0.15)),
            g(40, 12), g(0, 3), min(1.0, max(0.7, g(0.95, 0.05))), abs(g(110, 35)),
            1, 0, g(0, 0.8), g(0, 0.8), g(0, 0.8), g(0, 0.8), g(0, 0.8), g(0, 0.8)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    r = random.Random(1)
    with open(sys.argv[1], "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(edge_model.FEATURE_NAMES)
        for _ in range(n):
            w.writerow([round(x, 4) for x in row(r)])
    print(f"wrote {n} synthetic rows to {sys.argv[1]}")


if __name__ == "__main__":
    main()
