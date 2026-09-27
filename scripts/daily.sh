#!/usr/bin/env bash
# The daily run, as the systemd timer starts it. Safe to start any number of times:
#   - flock: a second start while one runs exits at once instead of doubling the CPU load;
#   - --skip-if-built: once today's (Berlin) digest exists, a catch-up start costs nothing.
# Output goes to the journal:  journalctl --user -u pulse-scout.service
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO/.venv/bin/python"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/pulse-scout-daily.lock"
OLLAMA="${OLLAMA_HOST:-http://localhost:11434}"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "another pulse-scout run holds $LOCK — not starting a second one"
  exit 0
fi

# A catch-up start right after WSL boots can beat Ollama to it. Wait up to two minutes
# rather than failing a run that would have worked a moment later.
for _ in $(seq 1 60); do
  if curl -sf "$OLLAMA/api/tags" >/dev/null; then
    break
  fi
  sleep 2
done

cd "$REPO"
exec "$PYTHON" scripts/build_digest.py --skip-if-built
