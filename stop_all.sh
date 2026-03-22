#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$REPO_DIR/logs/pids"

echo "════════════════════════════════════════"
echo "  Moonshot-CEX  —  Stopping All Services"
echo "════════════════════════════════════════"

stop_proc() {
  local name="$1"
  local pid_file="$2"
  local pattern="$3"
  local pids=""

  # 1) Try PID file first (most reliable)
  if [[ -f "$pid_file" ]]; then
    local file_pid
    file_pid=$(cat "$pid_file" 2>/dev/null || true)
    if [[ -n "$file_pid" ]] && kill -0 "$file_pid" 2>/dev/null; then
      pids="$file_pid"
    fi
    rm -f "$pid_file"
  fi

  # 2) Fallback: pgrep pattern
  if [[ -z "$pids" ]]; then
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
  fi

  if [[ -n "$pids" ]]; then
    echo "[INFO] Stopping $name (PIDs: $(echo $pids | tr '\n' ' '))..."
    # Send SIGTERM first, then SIGKILL after 2s
    kill $pids 2>/dev/null || true
    sleep 2
    kill -9 $pids 2>/dev/null || true
    echo "[OK] $name stopped"
  else
    echo "[SKIP] $name not running"
  fi
}

stop_proc "Backend (uvicorn)"  "$PID_DIR/backend.pid"  "uvicorn backend.server"
stop_proc "Frontend dashboard" "$PID_DIR/frontend.pid" "next.*(start|dev).*3001"
stop_proc "TinyOffice"         "$PID_DIR/tinyoffice.pid" "next.*(dev|start).*tinyoffice"

# Kill screen sessions (used for frontend/tinyoffice)
for sess in moonshot-frontend moonshot-tinyoffice; do
  if screen -ls | grep -q "$sess"; then
    echo "[INFO] Killing screen session: $sess"
    screen -S "$sess" -X quit 2>/dev/null || true
    echo "[OK] $sess screen stopped"
  fi
done

# Also kill any leftover next-server processes on our ports
for port in 3000 3001; do
  pid=$(lsof -ti:$port 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    echo "[INFO] Killing process on port $port (PID $pid)..."
    kill -9 $pid 2>/dev/null || true
  fi
done

echo ""
echo "[DONE] All Moonshot-CEX processes stopped."
echo "════════════════════════════════════════"
