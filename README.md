# Moonshot-CEX

> **Fully autonomous multi-agent crypto trading system for centralized exchanges.**  
> Runs 24/7 on Binance Futures, Gate.io, and KuCoin — paper, demo, or live.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?logo=fastapi)
![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=nextdotjs)
![MongoDB](https://img.shields.io/badge/MongoDB-6+-green?logo=mongodb)
![Redis](https://img.shields.io/badge/Redis-7+-red?logo=redis)
![License](https://img.shields.io/badge/License-Private-lightgrey)

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture](#architecture)
3. [Key Systems](#key-systems)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [Trading Modes](#trading-modes)
7. [API Reference](#api-reference)
8. [Project Structure](#project-structure)
9. [Observability](#observability)
10. [Tests](#tests)
11. [Safety](#safety)
12. [Changelog](#changelog)

---

## What It Does

Moonshot-CEX is a **production-grade autonomous trading swarm** that:

- Scans **548+ USDT perpetual futures pairs** every 30 seconds for emerging momentum
- Runs deep multi-timeframe TA (5m / 15m / 1h / 4h) on top candidates
- Filters entries through a **calibrated Bayesian probabilistic decision engine** with online prior updates
- Computes **dynamic leverage (3x–10x)** per trade based on signal confidence, regime, volume, win streak, and funding rate
- Sizes positions using **regime-dynamic, conviction-aware Half-Kelly** — 15% of wallet per position in sideways, 18% in bull, 10% in bear, 8% in choppy
- Manages the full position lifecycle: **trailing stops, tiered partial exits (1.5R / 3R), pyramid adds, and time-based exits**
- Detects market regime in real-time (bull / sideways / bear / choppy) and adapts **all parameters**: sizing, leverage, max positions, stop distances, exit timing
- **Self-tunes** — Bayesian priors update after every closed trade; QuantMutator adjusts entry thresholds based on rolling performance

### Supported Exchanges & Modes

| Exchange | Spot | Futures (USDT-M) | Demo/Testnet |
|----------|------|-------------------|--------------|
| **Binance** | ✅ | ✅ (primary) | ✅ |
| **Gate.io** | ✅ | ✅ | ✅ |
| **KuCoin** | ✅ | — | ✅ |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      MOONSHOT-CEX  v3.3                               │
│                                                                      │
│  ┌───────────────┐    ┌──────────────────────────────────────────┐   │
│  │  TinyOffice   │    │           FastAPI Backend                 │   │
│  │  (AI Chat)    │◄──►│           (server.py)                    │   │
│  └───────────────┘    │  ┌──────────────┐  ┌─────────────────┐   │   │
│                       │  │  SwarmLoop   │  │  REST + WS API  │   │   │
│  ┌───────────────┐    │  │  30s cycle   │  │  20+ endpoints  │   │   │
│  │  Dashboard    │◄──►│  └──────────────┘  └─────────────────┘   │   │
│  │  (Next.js)    │    │                                          │   │
│  └───────────────┘    │     AGENT PIPELINE (per cycle)           │   │
│                       │                                          │   │
│                       │  1. Watcher ──► 2. Analyzer ──► 3. Context│  │
│                       │       ↓                                   │   │
│                       │  4. Bayesian ──► 5. LeverageEngine        │   │
│                       │       ↓                                   │   │
│                       │  6. RiskManager ──► 7. ExecutionCore      │   │
│                       │       ↓                                   │   │
│                       │  8. PositionManager (tick all open)       │   │
│                       │       ↓                                   │   │
│                       │  9. BigBrother ──► 10. QuantMutator       │   │
│                       │       ↓                                   │   │
│                       │  11. Alerts ──► 12. WebSocket broadcast   │   │
│                       └──────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  ┌────────────┐     │
│  │ MongoDB  │  │  Redis   │  │ Binance CCXT  │  │ OpenRouter │     │
│  │ trades   │  │  cache   │  │ Futures API   │  │   LLM      │     │
│  └──────────┘  └──────────┘  └───────────────┘  └────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### Agent Roles

| Agent | File | Role |
|---|---|---|
| **WatcherAgent** | `src/watcher.py` | Scans 548+ pairs, ranks by 1h return + volume + momentum score |
| **AnalyzerAgent** | `src/analyzer.py` | Multi-TF TA (5m/15m/1h/4h) — RSI, MACD, EMA, ATR, OBV; momentum fast-track |
| **ContextAgent** | `src/context_agent.py` | LLM-powered sentiment, catalyst + risk enrichment via OpenRouter |
| **BayesianEngine** | `src/bayesian_engine.py` | Calibrated posterior probability → enter/skip/reject; online prior updates |
| **LeverageEngine** | `src/leverage_engine.py` | Dynamic leverage 3x–10x based on confidence, regime, volume, streak, funding |
| **ExecutionCore** | `src/execution_core.py` | CCXT order placement, market entries, limit-first exits, algo stop orders |
| **PositionManager** | `src/position_manager.py` | Full lifecycle: trailing stops, tiered exits, pyramid adds, time exits |
| **RiskManager** | `src/risk_manager.py` | Conviction-aware Kelly sizing, regime-dynamic caps, drawdown circuit breakers |
| **QuantMutator** | `src/quant_mutator.py` | Self-tunes Bayesian threshold + min TA score based on rolling win rate + PnL |
| **BigBrother** | `src/bigbrother.py` | Regime detector + supervisor — capital deployment, mode management, alerts |
| **Alerts** | `src/alerts.py` | Discord / Telegram trade notifications and regime change alerts |

---

## Key Systems

### Dynamic Leverage Engine

Every trade gets **individually computed leverage** (3x–10x) based on five weighted factors:

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| **Signal Confidence** | 50% | Bayesian posterior × TA score (non-linear power curve) |
| **Market Regime** | 20% | Bull (1.0) → Sideways (0.55) → Bear (0.25) → Choppy (0.20) |
| **24h Volume** | 10% | Liquidity proxy — higher volume = safer to lever up |
| **Win Streak / Drawdown** | 10% | Hot hand → more; drawdown >5% → aggressively reduce |
| **Funding Rate** | 10% | Expensive funding against direction → reduce leverage |

Account tier safety caps prevent excessive leverage on smaller accounts:
- **< $2K**: max 5x | **< $10K**: max 8x | **≥ $10K**: full 10x

### Regime-Dynamic Position Sizing

BigBrother detects the market regime every cycle and adjusts **all capital parameters**:

| Regime | Max Per Position | Max Positions | Size Multiplier | Capital Deployed |
|--------|-----------------|---------------|-----------------|------------------|
| **Bull** | 18% of equity | 8 | 1.05× | 95% |
| **Sideways** | 15% of equity | 6 | 0.92× | 82% |
| **Bear** | 10% of equity | 4 | 0.65× | 55% |
| **Choppy** | 8% of equity | 3 | 0.50× | 42% |

Position sizing pipeline:
1. **Half-Kelly base** with conviction, liquidity, and TA multipliers
2. **Regime size multiplier** scales the base
3. **Margin cap** = equity × regime `max_single_pct` → notional = margin × leverage
4. **Cash guard** ensures margin doesn't exceed 92% of available balance

### Exit System

Simplified, battle-tested exit stack (priority order):

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| **Stop Loss** | PnL ≤ −3.5% | Full close (market sell) |
| **Trailing Stop** | Activates at +1.0%, trails 1.0% below peak | Full close (market sell) |
| **Momentum Faded** | Peak ≥ 3%, gave back 60%+, PnL < 0.5% | Full close |
| **Time Exit** | Hold > 3h AND PnL ≤ 0% | Full close (losers only) |
| **Time Exit Max** | Hold > 6h | Full close (hard ceiling) |
| **Tier 1** | R-multiple ≥ 1.5 | Partial exit (30%) |
| **Tier 2** | R-multiple ≥ 3.0 | Partial exit (25%) |

All stop/trailing exits use **market sell** for guaranteed fills. Regime scaling adjusts distances (bull: wider, bear: tighter).

### Bayesian Decision Engine

Every candidate setup is scored through Bayes' theorem:

```
posterior = (prior × ta_likelihood × context_likelihood × volume_likelihood × rr_factor) / normalization
```

- **Priors** update online after each closed trade (win → prior increases, loss → decreases)
- **Thresholds** are regime-aware: normal=0.45, volatile=0.47, safety=0.58
- **QuantMutator** adjusts thresholds dynamically based on rolling performance (bounded 0.40–0.58)

---

## Quick Start

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| MongoDB | 6+ |
| Redis | 7+ |

### Setup

```bash
git clone https://github.com/codebytelabs/Moonshot-CEX.git
cd Moonshot-CEX

# Python backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Dashboard
cd frontend && npm install && cd ..

# TinyOffice AI chat
cd tinyclaw/tinyoffice && npm install && cd ../..

# Configure
cp .env.example .env
# → Fill in: BINANCE_API_KEY, BINANCE_API_SECRET, OPENROUTER_API_KEY
```

### Run

```bash
./start_all.sh        # starts backend + frontend + TinyOffice
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3001 |
| TinyOffice | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |

```bash
./stop_all.sh         # graceful shutdown (positions stay open)
./restart_all.sh      # stop + start
```

### Docker (alternative)

```bash
docker compose up -d
```

---

## Configuration

All parameters live in `.env`. Key sections below — see `.env.example` for all ~120 parameters with inline docs.

### Exchange
```env
EXCHANGE_NAME=binance          # binance | gateio | kucoin
EXCHANGE_MODE=demo             # paper | demo | live
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

> ⚠️ Equity is always fetched live from the exchange at startup. The system refuses to trade until a valid equity value is confirmed from the futures wallet.

### Risk & Sizing
```env
MAX_POSITIONS=8                    # absolute ceiling (regime overrides lower)
MAX_PORTFOLIO_EXPOSURE_PCT=0.90    # 90% max deployed
MAX_SINGLE_EXPOSURE_PCT=0.20       # 20% absolute ceiling (regime caps: 8-18%)
MAX_RISK_PER_TRADE_PCT=0.08        # 8% risk per trade
MAX_DRAWDOWN_PCT=0.25              # 25% drawdown halt
DAILY_LOSS_LIMIT_PCT=0.05          # 5% daily loss limit
CONSECUTIVE_LOSS_THRESHOLD=5       # pause after 5 consecutive losses
```

### Exit Rules
```env
STOP_LOSS_PCT=-3.5                 # -3.5% hard stop
TRAILING_STOP_ACTIVATE_PCT=1.0     # trailing activates at +1%
TRAILING_STOP_DISTANCE_PCT=1.0     # trails 1% below peak
TAKE_PROFIT_TIER1_R=1.5            # exit 30% at 1.5R
TAKE_PROFIT_TIER2_R=3.0            # exit 25% at 3.0R
TIME_EXIT_HOURS=3.0                # close losers after 3h
SYMBOL_COOLDOWN_MINUTES=120        # 2h cooldown after closing a symbol
```

### Bayesian Thresholds
```env
BAYESIAN_THRESHOLD_NORMAL=0.45
BAYESIAN_THRESHOLD_VOLATILE=0.47
BAYESIAN_THRESHOLD_SAFETY=0.58
```

### LLM (Context Agent)
```env
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemini-2.5-flash-lite-preview-09-2025
```

---

## Trading Modes

| Mode | Description |
|---|---|
| `paper` | Simulated fills — zero exchange interaction, zero risk |
| `demo` | Real orders on exchange testnet (Binance Futures testnet / Gate.io demo) |
| `live` | Full production trading with real capital |

**Always validate with `paper` → `demo` before going `live`.**

---

## API Reference

### Swarm Control

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/swarm/status` | Full swarm status + agent metrics |
| `POST` | `/api/swarm/start` | Start trading loop |
| `POST` | `/api/swarm/stop` | Graceful stop |
| `POST` | `/api/swarm/emergency-stop` | Close all positions + halt |

### Portfolio & Trades

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/portfolio` | Live equity, PnL, open positions with leverage + margin |
| `GET` | `/api/positions` | Open positions (exchange-sourced, includes unrealized PnL) |
| `GET` | `/api/trades` | FIFO-computed realized PnL history |
| `GET` | `/api/performance` | Rolling 7-day metrics (win rate, expectancy, Sharpe) |

### Agents & Feed

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/agents` | Per-agent health + metrics |
| `GET` | `/api/feed` | Recent decisions + signals feed |
| `GET` | `/api/regime` | Current detected regime + parameters |

### Settings

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/settings` | Current config snapshot |
| `PATCH` | `/api/settings` | Hot-update strategy params (no restart needed) |

### Real-Time

| Type | Endpoint | Description |
|---|---|---|
| `WebSocket` | `/ws` | Live swarm state push every cycle |

Interactive docs: **http://localhost:8000/docs**

---

## Project Structure

```
Moonshot-CEX/
├── src/                        # Core agent modules
│   ├── config.py               # Pydantic settings — all env vars
│   ├── exchange_ccxt.py        # CCXT async exchange connector (spot + futures)
│   ├── watcher.py              # Market scanner (548+ pairs)
│   ├── analyzer.py             # Multi-TF technical analysis + momentum fast-track
│   ├── context_agent.py        # LLM sentiment enrichment (OpenRouter)
│   ├── bayesian_engine.py      # Bayesian decision engine with online prior updates
│   ├── leverage_engine.py      # Dynamic leverage computation (3x-10x)
│   ├── execution_core.py       # Order placement — market entries, limit-first exits
│   ├── position_manager.py     # Position lifecycle — trailing, tiers, pyramid, time
│   ├── risk_manager.py         # Kelly sizing + regime-dynamic caps + circuit breakers
│   ├── quant_mutator.py        # Adaptive threshold self-tuning
│   ├── bigbrother.py           # Regime detection + capital deployment supervisor
│   ├── strategy_manager.py     # Strategy routing and management
│   ├── performance_tracker.py  # Rolling performance metrics
│   ├── alerts.py               # Discord / Telegram notifications
│   ├── metrics.py              # Prometheus metric definitions
│   ├── redis_client.py         # Redis cache wrapper
│   └── logger.py               # Loguru structured logging
├── backend/
│   └── server.py               # FastAPI orchestrator — 12-step cycle + 20+ endpoints
├── frontend/                   # Next.js 15 dashboard (port 3001)
│   └── src/
│       ├── app/                # Pages: dashboard, positions, agents, settings, chat
│       └── components/         # NavChart, PositionsPanel, RegimePanel, TradeLog, etc.
├── tinyclaw/                   # TinyOffice AI chat interface (port 3000)
├── scripts/                    # Utility scripts (backtest, dust cleaner, close positions)
├── tests/                      # Pytest test suite (unit + integration + futures e2e)
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── start_all.sh / stop_all.sh / restart_all.sh
├── README.md
├── ARCHITECTURE.md             # Detailed system architecture
├── PRODUCT.md                  # Product specification
├── TECHNICAL.md                # Technical deep-dive
└── CHANGELOG.md                # Full version history
```

---

## Observability

| Layer | Tool | Details |
|---|---|---|
| **Metrics** | Prometheus | http://localhost:8000/metrics |
| **API Docs** | OpenAPI/Swagger | http://localhost:8000/docs |
| **Logs** | Loguru → file | `logs/backend.log` — structured, rotated, with leverage + sizing traces |
| **Database** | MongoDB | `positions`, `trades`, `agent_events`, `equity_history` collections |
| **Cache** | Redis | OHLCV, ticker, context caches (5-min TTL, ~95% hit rate) |
| **Alerts** | Discord / Telegram | Trade open/close, regime changes, circuit breaker trips |
| **Dashboard** | Next.js | Live NAV chart, positions panel, agent status, regime indicator |

**Key Prometheus metrics:**  
`account_equity` · `active_positions` · `current_drawdown` · `win_rate` · `decisions_made_total{outcome}` · `signals_generated_total{agent}` · `cycle_duration_seconds`

**Key log traces (per trade):**
```
[LevEngine] lev=8x | conf=0.77 reg=0.55 vol=1.00 streak=0.50 fund=0.90 composite=0.735
[Sizing] CHR/USDT:USDT FINAL notional=$5969 margin=$853 (lev=7x cap=15% regime=sideways)
```

---

## Tests

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Futures-specific tests
pytest tests/test_futures_e2e.py tests/test_futures_integration.py -v
```

| Test File | Coverage |
|---|---|
| `tests/test_risk_manager.py` | Conviction sizing, Kelly, circuit breakers, regime caps |
| `tests/test_bayesian_engine.py` | Posterior calculation, prior updates, threshold gating |
| `tests/test_position_manager.py` | Stop loss, trailing, tier exits, time exits, pyramid |
| `tests/test_api.py` | FastAPI endpoint integration |
| `tests/test_futures_e2e.py` | End-to-end futures order flow |
| `tests/test_futures_integration.py` | Futures wallet, leverage, margin verification |
| `tests/test_stop_loss_order.py` | Algo stop order placement via Binance API |

---

## Safety

- **Never run live without paper → demo validation first**
- API keys: enable **Futures Trading** only — **disable withdrawals**
- All secrets in `.env` — never committed (`.gitignore` enforced)
- Emergency stop: dashboard button or `POST /api/swarm/emergency-stop`
- **Circuit breakers**: daily loss limit (5%), max drawdown (25%), consecutive loss pause (5 losses → 20 min)
- **Account tier safety**: leverage capped by equity size (< $2K → max 5x, < $10K → max 8x)
- Exchange equity fetched and verified before any trade is allowed
- Futures positions recovered from exchange on restart (no orphaned positions)
- Market sell for all stop-loss and trailing-stop exits (guaranteed fills)

---

## Changelog

> Full version history: **[→ CHANGELOG.md](./CHANGELOG.md)**

### v3.3 — April 2026 (Current) — Dynamic Leverage & Regime-Dynamic Sizing

- **Dynamic Leverage Engine** (`src/leverage_engine.py`): 3x–10x per-trade leverage based on signal confidence (50%), regime (20%), volume (10%), win streak (10%), funding rate (10%); non-linear power curve amplifies quality differences; account tier safety caps
- **Regime-dynamic position sizing**: BigBrother sets per-regime `max_single_pct` (bull=18%, sideways=15%, bear=10%, choppy=8%) and max positions (8/6/4/3); server.py uses regime caps instead of static config
- **Bayesian posterior as confidence input** to leverage engine (was static 0.65 fallback)
- **Per-trade sizing + leverage logs**: `[Sizing] FINAL notional=$ margin=$ (lev=Xx cap=X% regime=X)`
- Updated `.env` defaults: `MAX_POSITIONS=8`, `MAX_SINGLE_EXPOSURE_PCT=0.20` (absolute ceiling)

### v3.2 — March 2026 — Profitability Overhaul

- Root cause analysis of 10+ systematic bugs; all fixed
- Simplified exit system: removed 7 underperforming momentum exits; trailing stop lowered to +1% activate / 1% trail
- Time exit only kills losers (profitable positions hold until trailing stop or tier exit)
- Quant Mutator threshold floors raised to prevent over-trading
- Bear/choppy dual-side trading; 4h EMA50 trend gate; momentum fast-track in analyzer

### v3.1 — March 2026 — Capital Deployment Overhaul

- Kelly sizing floor fix; account tier detection per-computation; min order $50
- Exposure limits updated for regime-aware deployment

### v3.0 — March 2026 — Exchange-First Architecture

- Exchange-first data; FIFO realized PnL; conviction/liquidity/TA multipliers in sizing
- Correct Bayesian inference replaces heuristic normalization
- Next.js dashboard with NAV chart (Session/1H/6H/1D/7D)

### v2.0 — March 2026

- Exchange holdings protection (stop loss + trailing + time exit); limit-first exits; symbol cooldowns

### v1.0 — Initial Release

- Multi-agent swarm; paper/demo/live modes; Gate.io/Binance/KuCoin; Next.js dashboard; MongoDB + Redis
