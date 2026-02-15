#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo ""
echo "Stopping Tech Assessment Hub..."
./scripts/stop_detached.sh || true

echo ""
read -r -p "Press Enter to close this window..."
