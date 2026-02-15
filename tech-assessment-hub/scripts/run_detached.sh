#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PIDFILE="data/server.pid"
URLFILE="data/server.url"
LOGFILE="data/server.log"

mkdir -p data

HOST="${TECH_ASSESSMENT_HUB_HOST:-127.0.0.1}"
START_PORT="${TECH_ASSESSMENT_HUB_PORT:-8080}"

# Prefer Python-based daemonization to survive IDE task terminals and avoid stale pidfiles.
if [[ -x "./venv/bin/python" ]]; then
  exec ./venv/bin/python ./scripts/daemon_start.py
fi

echo "Missing venv Python at ./venv/bin/python. Create the venv first (see README.md)."
exit 2
