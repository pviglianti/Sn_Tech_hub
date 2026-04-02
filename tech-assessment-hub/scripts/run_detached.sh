#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PIDFILE="data/server.pid"
URLFILE="data/server.url"
LOGFILE="data/server.log"

# If data/ is a symlink (e.g. to external SSD), verify the target is mounted
if [[ -L "./data" ]]; then
  link_target="$(readlink ./data)"
  if [[ ! -d "$link_target" ]]; then
    echo "Startup blocked: data/ symlink target is not available."
    echo ""
    echo "  Symlink: ./data -> $link_target"
    echo ""
    echo "Fix: plug in the external SSD and make sure it is mounted, then retry."
    exit 4
  fi
fi

mkdir -p data

HOST="${TECH_ASSESSMENT_HUB_HOST:-127.0.0.1}"
START_PORT="${TECH_ASSESSMENT_HUB_PORT:-8080}"

is_dataless() {
  local target="$1"
  local listing=""

  [[ -e "$target" ]] || return 1

  if ! listing="$(ls -ldO "$target" 2>/dev/null)"; then
    return 1
  fi

  [[ "$listing" == *"dataless"* ]]
}

declare -a dataless_paths=()
for path in \
  "./scripts/daemon_start.py" \
  "./src/server.py" \
  "./src/database.py" \
  "./data/tech_assessment.db"
do
  if is_dataless "$path"; then
    dataless_paths+=("$path")
  fi
done

# Check venv site-packages — offloaded metadata files crash Python at import time
if [[ -d "./venv" ]]; then
  while IFS= read -r -d '' venv_file; do
    if is_dataless "$venv_file"; then
      dataless_paths+=("$venv_file (venv)")
      break  # one is enough to know the venv needs downloading
    fi
  done < <(find ./venv/lib -maxdepth 4 -name "*.txt" -o -name "*.py" 2>/dev/null | head -20 | tr '\n' '\0')
fi

if ((${#dataless_paths[@]} > 0)); then
  echo "Startup blocked: required files are iCloud offloaded (dataless)."
  echo ""
  echo "Files:"
  for path in "${dataless_paths[@]}"; do
    echo "  - $path"
  done
  echo ""
  echo "Fix:"
  echo "  1) In Finder, right-click this project folder and choose Download Now (or Keep Downloaded)."
  echo "  2) Wait for iCloud sync to finish for these files."
  echo "  3) Free local disk space if sync cannot complete."
  echo "  4) Re-run ./start_app.command or ./restart_app.command."
  echo ""
  echo "Or run: find ./venv -type f -exec cat {} + > /dev/null 2>&1"
  exit 3
fi

# Prefer Python-based daemonization to survive IDE task terminals and avoid stale pidfiles.
if [[ -x "./venv/bin/python" ]]; then
  ./venv/bin/python ./scripts/daemon_start.py
  exit $?
fi

echo "Missing venv Python at ./venv/bin/python. Create the venv first (see README.md)."
exit 2
