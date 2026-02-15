#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PIDFILE="data/server.pid"
URLFILE="data/server.url"

if [[ ! -f "$PIDFILE" ]]; then
  echo "Not running (missing $PIDFILE)."
  exit 0
fi

PID="$(cat "$PIDFILE" || true)"
if [[ -z "${PID:-}" ]]; then
  rm -f "$PIDFILE"
  rm -f "$URLFILE"
  echo "Not running (empty pidfile)."
  exit 0
fi

if ! kill -0 "$PID" >/dev/null 2>&1; then
  rm -f "$PIDFILE"
  rm -f "$URLFILE"
  echo "Not running (stale pid=$PID)."
  exit 0
fi

CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
if [[ -z "${CMD:-}" ]] || [[ "$CMD" != *"uvicorn"* ]] || [[ "$CMD" != *"src.server:app"* ]]; then
  rm -f "$PIDFILE"
  rm -f "$URLFILE"
  echo "Not running (stale pidfile; pid=$PID now points to a different process)."
  exit 0
fi

kill "$PID"

for _ in $(seq 1 40); do
  if ! kill -0 "$PID" >/dev/null 2>&1; then
    rm -f "$PIDFILE"
    rm -f "$URLFILE"
    echo "Stopped (pid=$PID)."
    exit 0
  fi
  sleep 0.1
done

echo "Stop timed out; sending SIGKILL (pid=$PID)."
kill -9 "$PID" || true
rm -f "$PIDFILE"
rm -f "$URLFILE"
