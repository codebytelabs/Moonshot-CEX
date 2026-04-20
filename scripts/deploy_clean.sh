#!/usr/bin/env bash
# v7.8.1 clean-deploy helper.
#
# Runs on the VM. Pulls latest main, clears every __pycache__ under the repo,
# and restarts the bot service. Prevents stale-bytecode deploy drift — that
# class of bug cost us the BTC crash sweep during v7.8.
#
# Usage (on the VM):
#   bash scripts/deploy_clean.sh
#
# Exit codes:
#   0 = deploy + restart succeeded
#   1 = git pull failed (likely local changes or merge conflict)
#   2 = service failed to come back up cleanly

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/codebytelabs4/moonshot-cex}"
SERVICE_NAME="${SERVICE_NAME:-moonshot-bot.service}"
LOG_PATH="${LOG_PATH:-$REPO_DIR/logs/bot.log}"

echo "[deploy_clean] repo=$REPO_DIR service=$SERVICE_NAME"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "[deploy_clean] ERROR: $REPO_DIR is not a git checkout"
  exit 1
fi

echo "[deploy_clean] pulling latest main (fast-forward only)"
if ! git -C "$REPO_DIR" pull --ff-only origin main; then
  echo "[deploy_clean] ERROR: git pull failed — check local status on VM"
  git -C "$REPO_DIR" status --short
  exit 1
fi

echo "[deploy_clean] clearing stale __pycache__ directories"
find "$REPO_DIR" -path "*/\.venv" -prune -o -type d -name "__pycache__" -print -exec rm -rf {} + || true

echo "[deploy_clean] restarting $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

sleep 5

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "[deploy_clean] ERROR: $SERVICE_NAME did not come back up"
  systemctl --no-pager --full status "$SERVICE_NAME" | tail -n 40
  exit 2
fi

echo "[deploy_clean] service active. Tail of bot log:"
tail -n 20 "$LOG_PATH" || true

echo "[deploy_clean] done."
