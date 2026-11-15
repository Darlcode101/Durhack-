#!/bin/bash
# (Re)start the live duress dashboard on the UNO Q.
# If install_autostart.sh has set up the systemd service, restart that; otherwise start it
# detached by hand (logging to ~/dashboard.log).
set -e
cd "$(dirname "$0")/../.."
MODEL=app/dashboard/models/face_detection_yunet_2023mar.onnx
if [ ! -f "$MODEL" ]; then
  mkdir -p "$(dirname "$MODEL")"
  curl -sSL --max-time 60 -o "$MODEL" \
    https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
fi
URL="http://$(hostname -I | awk '{print $1}'):8080"
if systemctl --user is-enabled yuduino-dashboard.service >/dev/null 2>&1; then
  systemctl --user restart yuduino-dashboard.service
  echo "dashboard restarting (systemd): $URL  (logs: journalctl --user -u yuduino-dashboard -f)"
  exit 0
fi
# Uses kill -9 because an open browser video stream stops uvicorn from exiting on a normal kill.
pkill -9 -f "^$HOME/durhack-venv/bin/python app/dashboard/server.py" || true
sleep 1
setsid nohup "$HOME/durhack-venv/bin/python" app/dashboard/server.py > "$HOME/dashboard.log" 2>&1 < /dev/null &
echo "dashboard starting: $URL  (log: ~/dashboard.log)"
