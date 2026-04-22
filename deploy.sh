#!/usr/bin/env bash
# Deploy local tech-assessment-hub code to the GCE VM.
# Usage: ./deploy.sh [--restart-only]
#
# Safe to run anytime. Does NOT touch the VM database.
set -euo pipefail

VM_NAME="pvig-ta-2026"
VM_ZONE="us-central1-b"
REMOTE_APP_DIR="/opt/ta-hub/app"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CODE_DIR="$REPO_ROOT/tech-assessment-hub"
PLUGIN_DIR="$REPO_ROOT/assessment-plugin"
PLUGIN_ZIP="$REPO_ROOT/assessment-plugin.zip"

GCLOUD="${GCLOUD:-$(command -v gcloud || echo /opt/homebrew/bin/gcloud)}"
TARBALL="/tmp/ta-hub-deploy-$$.tgz"

log() { printf "\033[1;36m[deploy]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[deploy] FAIL:\033[0m %s\n" "$*" >&2; exit 1; }

if [[ "${1:-}" == "--restart-only" ]]; then
  log "restart only — skipping code push"
else
  [[ -d "$LOCAL_CODE_DIR" ]] || fail "code dir not found: $LOCAL_CODE_DIR"
  [[ -d "$PLUGIN_DIR" ]] || fail "plugin dir not found: $PLUGIN_DIR"

  # Rebuild assessment-plugin.zip from the folder so VM + plugin users run the
  # same artifact. Anyone editing SKILL.md files under assessment-plugin/ will
  # have their changes picked up automatically on the next deploy.
  log "rebuilding $PLUGIN_ZIP from $PLUGIN_DIR"
  rm -f "$PLUGIN_ZIP"
  ( cd "$REPO_ROOT" && zip -qr "$PLUGIN_ZIP" assessment-plugin \
      -x 'assessment-plugin/.DS_Store' 'assessment-plugin/**/.DS_Store' ) \
    || fail "zip rebuild failed"

  log "packing code from $LOCAL_CODE_DIR"
  tar czf "$TARBALL" \
    --exclude='.git' \
    --exclude='venv' --exclude='.venv' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude='*.db-journal' \
    --exclude='recovery_snapshots' \
    --exclude='data' \
    --exclude='.tech_assessment.db.*' --exclude='snapshot_*.db' \
    --exclude='.DS_Store' --exclude='node_modules' \
    --exclude='.pytest_cache' \
    -C "$LOCAL_CODE_DIR" .

  SIZE=$(du -h "$TARBALL" | awk '{print $1}')
  log "tarball built ($SIZE) — uploading to VM"
  "$GCLOUD" compute scp --zone="$VM_ZONE" "$TARBALL" "$VM_NAME:/tmp/ta-hub-deploy.tgz" >/dev/null 2>&1 \
    || fail "scp failed"

  log "uploading plugin zip to VM"
  "$GCLOUD" compute scp --zone="$VM_ZONE" "$PLUGIN_ZIP" "$VM_NAME:/tmp/assessment-plugin.zip" >/dev/null 2>&1 \
    || fail "plugin scp failed"

  log "extracting on VM"
  "$GCLOUD" compute ssh "$VM_NAME" --zone="$VM_ZONE" --command="
    set -e
    sudo tar xzf /tmp/ta-hub-deploy.tgz -C $REMOTE_APP_DIR
    sudo rm -rf $REMOTE_APP_DIR/data
    sudo ln -sfn /mnt/data $REMOTE_APP_DIR/data
    sudo rm -rf $REMOTE_APP_DIR/assessment-plugin
    sudo python3 -m zipfile -e /tmp/assessment-plugin.zip $REMOTE_APP_DIR
    sudo chown -R pviglianti:pviglianti $REMOTE_APP_DIR
    sudo -u pviglianti $REMOTE_APP_DIR/venv/bin/pip install -q -r $REMOTE_APP_DIR/requirements.txt
    sudo rm -f /tmp/ta-hub-deploy.tgz /tmp/assessment-plugin.zip
  " >/dev/null 2>&1 || fail "remote extract failed"

  rm -f "$TARBALL"
  log "code deployed"
fi

log "restarting service"
"$GCLOUD" compute ssh "$VM_NAME" --zone="$VM_ZONE" --command="sudo systemctl restart ta-hub" >/dev/null 2>&1 \
  || fail "service restart failed"

log "waiting 5s for service to come up"
sleep 5

log "health check"
HTTP_CODE=$("$GCLOUD" compute ssh "$VM_NAME" --zone="$VM_ZONE" \
  --command="curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/assessments" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" =~ ^(200|302|303|307|308)$ ]]; then
  log "✅ service healthy (HTTP $HTTP_CODE) — https://136-112-232-229.nip.io"
else
  log "⚠️  unexpected HTTP $HTTP_CODE — check logs:"
  "$GCLOUD" compute ssh "$VM_NAME" --zone="$VM_ZONE" --command="sudo tail -30 /var/log/ta-hub.log" 2>&1 | tail -30
  exit 1
fi
