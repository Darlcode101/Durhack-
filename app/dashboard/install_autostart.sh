#!/bin/bash
# Run ON THE UNO Q, once. Makes the demo come back by itself after any power blip:
#   * the App Lab sensor app (default: user:durhack-sensors) becomes App Lab's default app, started at boot
#   * the dashboard runs as a systemd user service: starts at boot, restarts if it crashes
# Logs:  journalctl --user -u yuduino-dashboard -f
set -euo pipefail
APP="${1:-user:durhack-sensors}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Face model (once)
MODEL="$HERE/models/face_detection_yunet_2023mar.onnx"
if [ ! -f "$MODEL" ]; then
  mkdir -p "$(dirname "$MODEL")"
  curl -sSL --max-time 60 -o "$MODEL" \
    https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
fi

echo "== sensor app at boot: $APP"
arduino-app-cli properties set default "$APP"
arduino-app-cli properties get default

echo "== dashboard service"
pkill -9 -f "^$HOME/durhack-venv/bin/python app/dashboard/server.py" || true   # stop a hand-started copy
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/yuduino-dashboard.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now yuduino-dashboard.service
sync
sleep 3
systemctl --user --no-pager --lines=0 status yuduino-dashboard.service | head -3
echo "Done. Dashboard: http://$(hostname -I | awk '{print $1}'):8080"
