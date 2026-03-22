#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_DIR/logs"
PID_DIR="$LOG_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

echo "════════════════════════════════════════"
echo "  Moonshot-CEX  —  Starting All Services"
echo "════════════════════════════════════════"

# ── 1. Check .env ────────────────────────────────────────────────────────────
if [[ ! -f "$REPO_DIR/.env" ]]; then
  echo "[ERROR] .env not found. Copy .env.example and fill in your keys."
  exit 1
fi
source "$REPO_DIR/.env"

# ── 2. Locate Python (venv or fallback) ──────────────────────────────────────
PYTHON=""
for _venv in \
    "$REPO_DIR/.venv" \
    "$(dirname "$REPO_DIR")/Moonshot/.venv" \
    "$HOME/.venv"; do
  if [[ -x "$_venv/bin/python" ]]; then
    PYTHON="$_venv/bin/python"
    echo "[OK] Python venv: $_venv"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  PYTHON="$(which python3 || which python)"
  echo "[WARN] No venv found — using system Python: $PYTHON"
fi

# ── 3. Start MongoDB (if not already running) ────────────────────────────────
if ! pgrep -x mongod >/dev/null 2>&1; then
  echo "[INFO] Starting MongoDB..."
  mongod --dbpath /data/db --logpath "$LOG_DIR/mongo.log" --fork || {
    echo "[WARN] mongod fork failed — ensure MongoDB is installed or use Docker"
  }
else
  echo "[OK] MongoDB already running"
fi

# ── 4. Start Redis (if not already running) ──────────────────────────────────
if ! pgrep -x redis-server >/dev/null 2>&1; then
  echo "[INFO] Starting Redis..."
  redis-server --daemonize yes --logfile "$LOG_DIR/redis.log" || {
    echo "[WARN] Redis start failed — ensure Redis is installed or use Docker"
  }
else
  echo "[OK] Redis already running"
fi

sleep 1

# ── 5. Start FastAPI backend ─────────────────────────────────────────────────
echo "[INFO] Starting backend (FastAPI)..."
nohup "$PYTHON" -m uvicorn backend.server:app \
  --host 0.0.0.0 \
  --port "${BACKEND_PORT:-8000}" \
  --log-level info \
  </dev/null >> "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PID_DIR/backend.pid"
echo "[OK] Backend PID=$BACKEND_PID — logs: $LOG_DIR/backend.log"

# Wait for backend to be ready (up to 15s)
for i in $(seq 1 15); do
  sleep 1
  if curl -sf "http://localhost:${BACKEND_PORT:-8000}/health" >/dev/null 2>&1; then
    echo "[OK] Backend health check passed (${i}s)"
    break
  fi
  if [[ $i -eq 15 ]]; then
    echo "[WARN] Backend did not respond after 15s — check $LOG_DIR/backend.log"
  fi
done

# ── 6. Start frontend dashboard ──────────────────────────────────────────────
FRONTEND_DIR="$REPO_DIR/frontend"
if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[INFO] Starting frontend dashboard..."
  if [[ -f "$FRONTEND_DIR/.next/BUILD_ID" ]]; then
    _FRONTEND_CMD="npm start"
  else
    echo "[WARN] No production build found — using dev mode (run 'cd frontend && npm run build' for faster startup)"
    _FRONTEND_CMD="npm run dev"
  fi
  screen -dmS moonshot-frontend bash -c "cd '$FRONTEND_DIR' && $_FRONTEND_CMD >> '$LOG_DIR/frontend.log' 2>&1"
  sleep 2
  FRONTEND_PID=$(screen -ls | grep moonshot-frontend | awk '{print $1}' | cut -d. -f1 || echo "")
  echo "[OK] Frontend (screen:moonshot-frontend) — http://localhost:3001"
else
  echo "[WARN] Frontend node_modules not found. Run: cd frontend && npm install && npm run build"
fi

# ── 7. Start TinyOffice (always dev mode — no build step needed) ──────────────
TINYOFFICE_DIR="$REPO_DIR/tinyclaw/tinyoffice"
if [[ -d "$TINYOFFICE_DIR/node_modules" ]]; then
  echo "[INFO] Starting TinyOffice..."
  screen -dmS moonshot-tinyoffice bash -c "cd '$TINYOFFICE_DIR' && npm run dev >> '$LOG_DIR/tinyoffice.log' 2>&1"
  echo "[OK] TinyOffice (screen:moonshot-tinyoffice) — http://localhost:3000"
else
  echo "[WARN] TinyOffice node_modules not found. Run: cd tinyclaw/tinyoffice && npm install"
fi

echo ""
echo "════════════════════════════════════════"
echo "  All services started."
echo "  Dashboard  → http://localhost:3001"
echo "  TinyOffice → http://localhost:3000"
echo "  API        → http://localhost:${BACKEND_PORT:-8000}/docs"
echo "  Logs dir   → $LOG_DIR"
echo "  PID files  → $PID_DIR"
echo "════════════════════════════════════════"
