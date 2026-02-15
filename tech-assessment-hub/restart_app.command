#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo ""
echo "Restarting Tech Assessment Hub..."
./scripts/restart_detached.sh
./scripts/open_app.sh || true

echo ""
read -r -p "Press Enter to close this window..."
