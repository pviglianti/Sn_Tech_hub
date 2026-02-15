#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

URLFILE="data/server.url"

if [[ -f "$URLFILE" ]]; then
  URL="$(cat "$URLFILE" || true)"
  if [[ -n "${URL:-}" ]]; then
    if [[ "$URL" != http://* ]] && [[ "$URL" != https://* ]]; then
      URL="http://$URL"
    fi
    open "$URL" || true
    echo "Opened: $URL"
    echo "Note: if you see an SSL protocol error, make sure you're using http:// (this app does not run HTTPS locally)."
    exit 0
  fi
fi

echo "Missing data/server.url. Start the server first with ./scripts/run_detached.sh"
exit 1
