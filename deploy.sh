#!/usr/bin/env bash
# Deploy local tech-assessment-hub code to the Azure VM.
# Usage: ./deploy.sh [--restart-only]
#
# Safe to run anytime. Does NOT touch the VM database
# (data lives on /mnt/data, symlinked into the app dir, excluded from the tarball).
#
# Override defaults via env vars if your setup differs:
#   VM_HOST=20.81.208.47 VM_USER=bvp-admin SSH_KEY=~/ssh/AI-Test1_key.pem ./deploy.sh
set -euo pipefail

VM_HOST="${VM_HOST:-20.81.208.47}"
VM_USER="${VM_USER:-bvp-admin}"
SSH_KEY="${SSH_KEY:-$HOME/ssh/AI-Test1_key.pem}"
REMOTE_APP_DIR="/opt/ta-hub/app"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CODE_DIR="$REPO_ROOT/tech-assessment-hub"
PLUGIN_DIR="$REPO_ROOT/assessment-plugin"
PLUGIN_ZIP="$REPO_ROOT/assessment-plugin.zip"

TARBALL="/tmp/ta-hub-deploy-$$.tgz"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

log() { printf "\033[1;36m[deploy]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[deploy] FAIL:\033[0m %s\n" "$*" >&2; exit 1; }

[[ -r "$SSH_KEY" ]] || fail "SSH key not readable: $SSH_KEY (set SSH_KEY env var if elsewhere)"

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
  # COPYFILE_DISABLE=1 stops macOS from baking ._* AppleDouble files into the tar.
  COPYFILE_DISABLE=1 tar czf "$TARBALL" \
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
  scp "${SSH_OPTS[@]}" "$TARBALL" "$VM_USER@$VM_HOST:/tmp/ta-hub-deploy.tgz" >/dev/null \
    || fail "scp failed"

  log "uploading plugin zip to VM"
  scp "${SSH_OPTS[@]}" "$PLUGIN_ZIP" "$VM_USER@$VM_HOST:/tmp/assessment-plugin.zip" >/dev/null \
    || fail "plugin scp failed"

  log "extracting on VM"
  ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" "
    set -e
    sudo tar xzf /tmp/ta-hub-deploy.tgz -C $REMOTE_APP_DIR
    sudo rm -rf $REMOTE_APP_DIR/data
    sudo ln -sfn /mnt/data $REMOTE_APP_DIR/data
    sudo rm -rf $REMOTE_APP_DIR/assessment-plugin
    sudo python3 -m zipfile -e /tmp/assessment-plugin.zip $REMOTE_APP_DIR
    sudo find $REMOTE_APP_DIR -name '._*' -delete
    sudo chown -R $VM_USER:$VM_USER $REMOTE_APP_DIR
    sudo -u $VM_USER $REMOTE_APP_DIR/venv/bin/pip install -q -r $REMOTE_APP_DIR/requirements.txt
    sudo rm -f /tmp/ta-hub-deploy.tgz /tmp/assessment-plugin.zip
  " >/dev/null || fail "remote extract failed"

  rm -f "$TARBALL"
  log "code deployed"
fi

log "restarting service"
ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" "sudo systemctl restart ta-hub" >/dev/null \
  || fail "service restart failed"

log "waiting 5s for service to come up"
sleep 5

log "health check"
HTTP_CODE=$(ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" \
  "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/assessments" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" =~ ^(200|302|303|307|308)$ ]]; then
  log "✅ service healthy (HTTP $HTTP_CODE) on $VM_HOST"
else
  log "⚠️  unexpected HTTP $HTTP_CODE — check logs:"
  ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" "sudo tail -30 /var/log/ta-hub.log" 2>&1 | tail -30
  exit 1
fi
