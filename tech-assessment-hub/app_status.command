#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo ""
./scripts/status_detached.sh || true

echo ""
read -r -p "Press Enter to close this window..."
