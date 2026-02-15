#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo ""
echo "Starting Tech Assessment Hub..."
./scripts/run_detached.sh
./scripts/open_app.sh || true

echo ""
echo "Tip: if you ever need it:"
echo "  - Restart: ./restart_app.command"
echo "  - Stop:    ./stop_app.command"
echo "  - Status:  ./app_status.command"
echo ""
read -r -p "Press Enter to close this window..."
