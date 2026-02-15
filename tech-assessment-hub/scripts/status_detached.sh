#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PIDFILE="data/server.pid"
URLFILE="data/server.url"

if [[ ! -f "$PIDFILE" ]]; then
  echo "Not running."
  exit 1
fi

PID="$(cat "$PIDFILE" || true)"
if [[ -n "${PID:-}" ]] && kill -0 "$PID" >/dev/null 2>&1; then
  CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
  if [[ -z "${CMD:-}" ]] || [[ "$CMD" != *"uvicorn"* ]] || [[ "$CMD" != *"src.server:app"* ]]; then
    rm -f "$PIDFILE" "$URLFILE"
    echo "Not running (stale pidfile; pid=$PID now points to a different process)."
    exit 1
  fi

  if [[ -f "$URLFILE" ]]; then
    URL="$(cat "$URLFILE" || true)"
    if [[ -n "${URL:-}" ]]; then
      if curl -fsS --max-time 1 "$URL/api/mcp/health" >/dev/null 2>&1; then
        echo "Running (pid=$PID) at $URL"
        exit 0
      fi
      if curl -fsS --max-time 1 "$URL/" >/dev/null 2>&1; then
        echo "Running (pid=$PID) at $URL"
        exit 0
      fi
      echo "Running (pid=$PID) but unreachable at $URL (use http://, not https://)."
      exit 2
    fi
  fi
  echo "Running (pid=$PID)."
  exit 0
fi

echo "Not running (stale pidfile pid=${PID:-})."
exit 1
