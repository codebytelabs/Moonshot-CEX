#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  clean_dust.sh — One-click exchange dust sweeper
#
#  Usage:
#    ./scripts/clean_dust.sh               # dry-run (safe, shows what WOULD happen)
#    ./scripts/clean_dust.sh --execute     # actually sweep dust (places real orders)
#
#  Optional overrides:
#    ./scripts/clean_dust.sh --execute --dust-threshold 100  # treat < $100 as dust
#    ./scripts/clean_dust.sh --execute --min-notional 12     # use $12 as min notional
#    ./scripts/clean_dust.sh --execute --min-value 2         # only clean dust >= $2 current value
#
#  How it works:
#    1. Finds all non-stablecoin holdings < DUST_THRESHOLD (default $50)
#    2. If a holding is below MIN_NOTIONAL ($10.5 default): buys just enough first
#    3. Then market-sells everything in one pass
#
#  Run from the project root or from anywhere — the script resolves paths itself.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Locate Python venv ────────────────────────────────────────────────────────
PYTHON=""
if [[ -f "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "[ERROR] Python not found. Activate your venv or install Python 3." >&2
    exit 1
fi

# ── Load .env if dotenv CLI available (optional, Python handles it too) ───────
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo "[INFO] Loading .env from $PROJECT_ROOT"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Moonshot-CEX — Dust Cleaner"
echo "  Exchange: ${EXCHANGE_NAME:-$(grep ^EXCHANGE_NAME "$PROJECT_ROOT/.env" 2>/dev/null | cut -d= -f2 || echo 'see .env')}"
echo "  Mode:     ${EXCHANGE_MODE:-$(grep ^EXCHANGE_MODE "$PROJECT_ROOT/.env" 2>/dev/null | cut -d= -f2 || echo 'see .env')}"
echo "════════════════════════════════════════════════════════════"
echo ""

# Pass all CLI args directly to the Python script
cd "$PROJECT_ROOT"
"$PYTHON" scripts/dust_cleaner.py "$@"
