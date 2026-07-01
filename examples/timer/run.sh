#!/usr/bin/env bash
# examples/timer/run.sh — countdown timer rendered on the LED strip.
#
# Usage:
#   ./run.sh <duration>       # 30, 30s, 5m, 1h30m, ...
#
# Renders the remaining time as a shrinking level bar via the firmware's
# `level` animation. Color interpolates green (full) → red (empty). Updates
# once per second. Each tick is sent as a persistent STATE under a per-invocation
# session id so the latest level wins; the session is cleared on exit.
#
# Requires the daemon running and `led` on $PATH (after ./scripts/install.sh).

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <duration>  (e.g. 30, 30s, 5m, 1h30m)" >&2
  exit 1
fi

# Parse "1h30m", "5m", "90s", or "90" into total seconds. Bare trailing digits
# are interpreted as seconds.
parse_duration() {
  local s="$1" total=0 num="" i ch
  for ((i = 0; i < ${#s}; i++)); do
    ch="${s:$i:1}"
    case "$ch" in
      [0-9]) num+="$ch" ;;
      [sS])  [[ -n "$num" ]] || return 1; total=$((total + num));     num="" ;;
      [mM])  [[ -n "$num" ]] || return 1; total=$((total + num * 60));  num="" ;;
      [hH])  [[ -n "$num" ]] || return 1; total=$((total + num * 3600)); num="" ;;
      *) return 1 ;;
    esac
  done
  [[ -n "$num" ]] && total=$((total + num))
  ((total > 0)) || return 1
  echo "$total"
}

total=$(parse_duration "$1") || {
  echo "invalid duration: $1 (try 30, 30s, 5m, or 1h30m)" >&2
  exit 1
}

SESSION="timer-$$"
trap 'led --quiet --end-session "$SESSION" 2>/dev/null || true' EXIT

end=$(( $(date +%s) + total ))
while :; do
  now=$(date +%s)
  remaining=$(( end - now ))
  (( remaining > 0 )) || break

  pct=$(( remaining * 100 / total ))
  r=$(( (100 - pct) * 255 / 100 ))
  g=$(( pct * 255 / 100 ))

  led --quiet --session "$SESSION" --raw level --rgb "$r,$g,0" --level "$pct"
  sleep 1
done
