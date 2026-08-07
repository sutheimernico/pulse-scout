#!/usr/bin/env bash
# SessionStart hook for pulse-scout.
#
# Prints where the project stands and what the single next step is, derived from the
# repository itself rather than from a hand-maintained status line — a status line someone
# forgets to update is worse than none.
#
# Registered in ~/private/.claude/settings.local.json so it fires for any session under
# ~/private. Must stay fast (10s timeout) and quiet when there is nothing to say.

set -uo pipefail

REPO="$HOME/private/pulse-scout"
[ -d "$REPO" ] || exit 0

cd "$REPO" 2>/dev/null || exit 0

# --- derive state from the repo ---------------------------------------------------------

open_tasks=$(grep -c '^\s*- \[ \]' PLAN.md 2>/dev/null || echo 0)
done_tasks=$(grep -c '^\s*- \[x\]' PLAN.md 2>/dev/null || echo 0)

# A plan document under docs/superpowers/plans/ is what unblocks the backlog.
plan_count=$(find docs/superpowers/plans -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

# Source modules beyond the config loader mean implementation has actually started.
modules=$(find src/pulse_scout -maxdepth 1 -name '*.py' ! -name '__init__.py' 2>/dev/null | wc -l | tr -d ' ')

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
last=$(git log -1 --format='%h %s' 2>/dev/null | cut -c1-64)
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

# --- decide the single next step --------------------------------------------------------

if [ "$plan_count" -eq 0 ]; then
  next="Spec gegenlesen, dann Umsetzungsplan schreiben (writing-plans). Backlog ist bis dahin bewusst leer."
  phase="Phase 0 — Gerüst steht, wartet auf Plan"
elif [ "$open_tasks" -eq 0 ] && [ "$modules" -le 1 ]; then
  next="Plan liegt, aber PLAN.md hat keine offenen Aufgaben — Backlog aus dem Plan befüllen."
  phase="Phase 0/1 — Übergang"
elif [ "$open_tasks" -gt 0 ]; then
  first_open=$(grep -m1 '^\s*- \[ \]' PLAN.md 2>/dev/null | sed 's/^\s*- \[ \]\s*//' | cut -c1-70)
  next="Nächste Aufgabe: ${first_open}"
  phase="Phase 1+ — ${done_tasks} erledigt, ${open_tasks} offen"
else
  next="Kein offener Punkt im Backlog. Läuft der Digest im Alltag? Sonst Stufe 2 angehen."
  phase="Backlog leer"
fi

# --- output -----------------------------------------------------------------------------

printf '[pulse-scout] %s\n' "$phase"
printf '[pulse-scout] %s\n' "$next"
printf '[pulse-scout] Branch %s · zuletzt: %s' "$branch" "${last:-—}"
[ "$dirty" -gt 0 ] && printf ' · %s Datei(en) uncommitted' "$dirty"
printf '\n'

# Offene Nico-Entscheidungen nur nennen, solange sie offen sind.
if ! git remote 2>/dev/null | grep -q .; then
  printf '[pulse-scout] Needs Nico: Git-Remote + Sichtbarkeit noch nicht entschieden (kein Remote gesetzt).\n'
fi

# Das Mockup ist nur erreichbar, solange der kleine Server läuft — sonst gar nicht erwähnen.
if command -v ss >/dev/null 2>&1 && ss -lntH 2>/dev/null | grep -q ':8430 '; then
  printf '[pulse-scout] Mockup läuft: http://<tailscale-ip>:8430/ (Tailscale)\n'
fi

exit 0
