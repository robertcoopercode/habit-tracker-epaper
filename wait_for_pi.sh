#!/usr/bin/env bash
set -u

HOST="${1:-${HABIT_PI_HOST:-raspberrypi.local}}"
INTERVAL_SECONDS="${2:-2}"

echo "Waiting for host to resolve + respond: $HOST"
echo "Polling every ${INTERVAL_SECONDS}s. Ctrl+C to stop."

while true; do
  # -c 1: one ping, -W 1000: 1s timeout (macOS)
  if ping -c 1 -W 1000 "$HOST" >/dev/null 2>&1; then
    echo "OK: $HOST is reachable."
    exit 0
  fi

  # Optional: show a simple heartbeat with timestamp
  printf "[%s] still waiting...\n" "$(date '+%Y-%m-%d %H:%M:%S')"
  sleep "$INTERVAL_SECONDS"
done