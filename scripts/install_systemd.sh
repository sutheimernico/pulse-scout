#!/usr/bin/env bash
# Install (or update) the pulse-scout user units. Idempotent: copy, reload, enable.
#   bash scripts/install_systemd.sh
# Undo:
#   systemctl --user disable --now pulse-scout.timer pulse-scout-web.service
#   rm ~/.config/systemd/user/pulse-scout{.service,.timer,-web.service}
#   systemctl --user daemon-reload
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

for unit in pulse-scout.service pulse-scout.timer pulse-scout-web.service; do
  cp "$REPO/deploy/$unit" "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload

systemctl --user enable --now pulse-scout.timer

# The web unit fails closed without a token; enabling it without one would only crash-loop.
if grep -Eq '^PULSE_DASH_TOKEN=.+' "$REPO/.env" 2>/dev/null; then
  systemctl --user enable pulse-scout-web.service
  systemctl --user restart pulse-scout-web.service
else
  echo "PULSE_DASH_TOKEN is not set in $REPO/.env — web service installed but NOT enabled."
fi

systemctl --user list-timers pulse-scout.timer --no-pager
systemctl --user --no-pager --lines=0 status pulse-scout-web.service || true
