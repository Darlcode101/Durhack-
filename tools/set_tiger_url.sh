#!/bin/bash
# Put your Tiger Cloud connection URL into the UNO Q's .env and restart the dashboard.
# Run on your laptop:   tools/set_tiger_url.sh [board-address]      (default 172.20.10.2)
#
# The URL contains your database password, so:
#   * it is typed hidden (not echoed, not in shell history, not on any command line)
#   * it travels to the board over SSH (encrypted) on stdin
#   * on the board it is written to ~/Durhack-/.env with permissions 600, replacing any old value
set -euo pipefail
BOARD="${1:-172.20.10.2}"

if ! nc -z -G 3 "$BOARD" 22 2>/dev/null; then
  echo "Can't reach the board at $BOARD. Is this Mac on the same hotspot as the board?"
  exit 1
fi

echo "Paste your Tiger Cloud service URL (starts with postgres://), then press Enter."
echo "It won't be shown as you paste."
read -rs URL
echo
URL="$(printf '%s' "$URL" | tr -d '[:space:]')"
case "$URL" in
  postgres://*|postgresql://*) ;;
  *) echo "That doesn't look like a Tiger/Postgres URL (it should start with postgres://). Nothing changed."; exit 1 ;;
esac

printf '%s\n' "$URL" | ssh -o ConnectTimeout=8 "arduino@$BOARD" '
  set -e
  ENV="$HOME/Durhack-/.env"
  touch "$ENV"; chmod 600 "$ENV"
  IFS= read -r URL
  grep -v "^TIGER_DATABASE_URL=" "$ENV" > "$ENV.tmp" || true
  printf "TIGER_DATABASE_URL=%s\n" "$URL" >> "$ENV.tmp"
  chmod 600 "$ENV.tmp"; mv "$ENV.tmp" "$ENV"; sync
  echo "Saved to .env on the board."
  if [ -x "$HOME/Durhack-/app/dashboard/restart.sh" ]; then "$HOME/Durhack-/app/dashboard/restart.sh"; fi
'
unset URL
echo "Done. Give it ~15 s, then open the dashboard: the Tiger Cloud pill should turn green."
