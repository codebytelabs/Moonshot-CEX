#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Moonshot-CEX  —  VM2 Remote Control
#  Usage:  ./scripts/vm2.sh <command>
#
#  Commands:
#    status      Show service status + equity + positions
#    start       Start bot + frontend + nginx
#    stop        Stop bot + frontend
#    restart     Restart bot + frontend + nginx
#    logs        Tail live bot logs (Ctrl+C to exit)
#    errors      Show last 50 error log lines
#    deploy      Git pull latest code + rebuild frontend + restart
#    ssh         Open interactive SSH session
#    health      Quick health check (API + equity)
#    sync-env    Copy local .env to VM2 and restart bot
# ─────────────────────────────────────────────────────────────

set -euo pipefail

VM_IP="85.9.198.137"
VM_USER="root"
SSH_KEY="$HOME/.ssh/google_compute_engine"
BOT_DIR="/home/codebytelabs4/moonshot-cex"
SERVICE_BOT="moonshot-bot.service"
SERVICE_FRONT="moonshot-frontend.service"

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $VM_USER@$VM_IP"

# ── Helpers ──────────────────────────────────────────────────

red()    { printf "\033[0;31m%s\033[0m\n" "$*"; }
green()  { printf "\033[0;32m%s\033[0m\n" "$*"; }
cyan()   { printf "\033[0;36m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

remote() {
  $SSH_CMD "$@"
}

# ── Commands ─────────────────────────────────────────────────

cmd_status() {
  bold "═══ Moonshot-CEX VM2 Status ═══"
  $SSH_CMD 'bash -s' <<'REMOTE_EOF'
echo "── Services ──"
printf "  Bot:      "; systemctl is-active moonshot-bot.service
printf "  Frontend: "; systemctl is-active moonshot-frontend.service
printf "  Nginx:    "; systemctl is-active nginx
printf "  MongoDB:  "; systemctl is-active mongod
printf "  Redis:    "; systemctl is-active redis-server

echo ""
echo "── Ports ──"
ss -tlnp | grep -E ':(8080|3001|8888) ' | awk '{print "  " $4}'

echo ""
echo "── Bot ──"
python3 -c '
import json, urllib.request
try:
    r = urllib.request.urlopen("http://localhost:8080/api/portfolio", timeout=5)
    d = json.loads(r.read())
    e = d.get("equity", 0)
    p = len(d.get("open_positions", []))
    t = d.get("today_pnl", 0)
    print("  Equity:    " + format(e, ",.2f"))
    print("  Positions: " + str(p) + " open")
    print("  Today PnL: " + format(t, ",.2f"))
except Exception as ex:
    print("  API not responding: " + str(ex))
'

echo ""
echo "── Last 3 log lines ──"
tail -3 /home/codebytelabs4/moonshot-cex/logs/bot.log 2>/dev/null || echo "  No logs"
REMOTE_EOF
}

cmd_start() {
  bold "Starting Moonshot-CEX on VM2..."
  remote "
    systemctl start $SERVICE_BOT
    systemctl start $SERVICE_FRONT
    systemctl start nginx
    sleep 3
    printf 'Bot:      '; systemctl is-active $SERVICE_BOT
    printf 'Frontend: '; systemctl is-active $SERVICE_FRONT
    printf 'Nginx:    '; systemctl is-active nginx
  "
  green "✅ Started"
}

cmd_stop() {
  bold "Stopping Moonshot-CEX on VM2..."
  remote "
    systemctl stop $SERVICE_BOT
    systemctl stop $SERVICE_FRONT
    printf 'Bot:      '; systemctl is-active $SERVICE_BOT || true
    printf 'Frontend: '; systemctl is-active $SERVICE_FRONT || true
  "
  green "✅ Stopped (nginx still running)"
}

cmd_restart() {
  bold "Restarting Moonshot-CEX on VM2..."
  remote "
    systemctl restart $SERVICE_BOT
    systemctl restart $SERVICE_FRONT
    systemctl restart nginx
    sleep 5
    printf 'Bot:      '; systemctl is-active $SERVICE_BOT
    printf 'Frontend: '; systemctl is-active $SERVICE_FRONT
    printf 'Nginx:    '; systemctl is-active nginx
  "
  green "✅ Restarted"
}

cmd_logs() {
  bold "Tailing bot logs (Ctrl+C to exit)..."
  $SSH_CMD "tail -f $BOT_DIR/logs/bot.log"
}

cmd_errors() {
  bold "Last 50 error log lines:"
  remote "tail -50 $BOT_DIR/logs/bot_error.log 2>/dev/null || echo 'No error log'"
}

cmd_deploy() {
  bold "Deploying latest code to VM2..."
  cyan "1/4  Git pull..."
  remote "sudo -u codebytelabs4 bash -c 'cd $BOT_DIR && git pull origin main 2>&1'"

  cyan "2/4  Install Python deps..."
  remote "sudo -u codebytelabs4 bash -c 'cd $BOT_DIR && source .venv/bin/activate && pip install -r requirements.txt -q 2>&1 | tail -3'"

  cyan "3/4  Build frontend..."
  remote "sudo -u codebytelabs4 bash -c 'cd $BOT_DIR/frontend && npm install --production 2>&1 | tail -3 && NEXT_PUBLIC_ADMIN_KEY=moonshot2024x npm run build 2>&1 | tail -10'"

  cyan "4/4  Restart services..."
  remote "
    systemctl restart $SERVICE_BOT
    systemctl restart $SERVICE_FRONT
    systemctl restart nginx
    sleep 5
    printf 'Bot:      '; systemctl is-active $SERVICE_BOT
    printf 'Frontend: '; systemctl is-active $SERVICE_FRONT
  "
  green "✅ Deployed and restarted"
}

cmd_ssh() {
  bold "Opening SSH to VM2..."
  $SSH_CMD
}

cmd_health() {
  $SSH_CMD 'bash -s' <<'REMOTE_EOF'
python3 -c '
import json, urllib.request
try:
    r = urllib.request.urlopen("http://localhost:8080/api/portfolio", timeout=5)
    d = json.loads(r.read())
    print("Bot:      OK | Equity: " + format(d.get("equity", 0), ",.2f"))
except Exception as ex:
    print("Bot:      FAIL | " + str(ex))
try:
    r = urllib.request.urlopen("http://localhost:3001/", timeout=5)
    print("Frontend: OK | HTTP " + str(r.status))
except Exception as ex:
    print("Frontend: FAIL | " + str(ex))
'
REMOTE_EOF
}

cmd_tunnel() {
  bold "Cloudflare Tunnel URL:"
  $SSH_CMD 'bash -s' <<'REMOTE_EOF'
URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /home/codebytelabs4/moonshot-cex/logs/tunnel.log 2>/dev/null | tail -1)
if [ -n "$URL" ]; then
  echo "  $URL"
  echo ""
  echo "  Status: $(systemctl is-active moonshot-tunnel.service)"
else
  echo "  No tunnel URL found. Is the tunnel running?"
  echo "  Status: $(systemctl is-active moonshot-tunnel.service)"
fi
REMOTE_EOF
}

cmd_tunnel_restart() {
  bold "Restarting Cloudflare Tunnel (URL will change)..."
  remote "
    rm -f /home/codebytelabs4/moonshot-cex/logs/tunnel.log
    systemctl restart moonshot-tunnel.service
    sleep 6
  "
  cmd_tunnel
}

cmd_sync_env() {
  bold "Syncing local .env to VM2..."
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  REPO_ROOT="$(dirname "$SCRIPT_DIR")"
  scp -i "$SSH_KEY" "$REPO_ROOT/.env" "$VM_USER@$VM_IP:$BOT_DIR/.env"
  remote "chown codebytelabs4:codebytelabs4 $BOT_DIR/.env"
  green "✅ .env synced"
  cyan "Restarting bot with new config..."
  remote "systemctl restart $SERVICE_BOT && sleep 5 && printf 'Bot: '; systemctl is-active $SERVICE_BOT"
  green "✅ Bot restarted with updated .env"
}

# ── Main ─────────────────────────────────────────────────────

case "${1:-}" in
  status)          cmd_status ;;
  start)           cmd_start ;;
  stop)            cmd_stop ;;
  restart)         cmd_restart ;;
  logs)            cmd_logs ;;
  errors)          cmd_errors ;;
  deploy)          cmd_deploy ;;
  ssh)             cmd_ssh ;;
  health)          cmd_health ;;
  tunnel)          cmd_tunnel ;;
  tunnel-restart)  cmd_tunnel_restart ;;
  sync-env)        cmd_sync_env ;;
  *)
    bold "Moonshot-CEX VM2 Remote Control"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  status          Show service status, equity, positions"
    echo "  start           Start bot + frontend + nginx"
    echo "  stop            Stop bot + frontend"
    echo "  restart         Restart all services"
    echo "  logs            Tail live bot logs (Ctrl+C to exit)"
    echo "  errors          Show last 50 error log lines"
    echo "  deploy          Git pull + rebuild + restart (full deploy)"
    echo "  ssh             Open interactive SSH session to VM2"
    echo "  health          Quick health check"
    echo "  tunnel          Show current Cloudflare tunnel HTTPS URL"
    echo "  tunnel-restart  Restart tunnel (URL will change)"
    echo "  sync-env        Copy local .env to VM2 + restart bot"
    ;;
esac
