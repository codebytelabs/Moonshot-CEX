# Moonshot-CEX

> **Fully autonomous multi-agent crypto trading system for centralized exchanges.**  
> Runs 24/7 on Gate.io, Binance, and KuCoin — paper, demo, or live.

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
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [Trading Modes](#trading-modes)
6. [API Reference](#api-reference)
7. [Project Structure](#project-structure)
8. [Observability](#observability)
9. [Tests](#tests)
10. [Safety](#safety)
11. [Changelog](#changelog)

---

## What It Does

Moonshot-CEX is a **production-grade autonomous trading swarm** that:

- Scans 150+ USDT pairs every 30 seconds for emerging momentum
- Runs deep multi-timeframe TA (5m / 15m / 1h / 4h) on top candidates
- Filters entries through a calibrated Bayesian probabilistic decision engine
- Sizes positions using **conviction-aware, liquidity-gated Half-Kelly** — high-confidence trades on liquid coins get up to 1.45× capital; borderline trades on illiquid coins as low as 0.26×
- Manages the full position lifecycle: tiered exits at 2R + 5R, trailing stop, pyramid adds, momentum-loss cuts, and time-based exits
- Adapts thresholds and exit parameters in real-time based on detected market regime (bull / sideways / bear)
- Learns online — Bayesian priors update after every closed trade

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     MOONSHOT-CEX  v3.0                           │
│                                                                  │
│  ┌───────────────┐    ┌────────────────────────────────────────┐ │
│  │  TinyOffice   │    │          FastAPI Backend                │ │
│  │  (Chat UI)   │◄──►│          (server.py)                   │ │
│  └───────────────┘    │  ┌──────────────┐  ┌───────────────┐  │ │
│                       │  │  SwarmLoop   │  │  REST + WS    │  │ │
│  ┌───────────────┐    │  │  30s cycle   │  │  API          │  │ │
│  │  Dashboard    │◄──►│  └──────────────┘  └───────────────┘  │ │
│  │  (Next.js)   │    │                                        │ │
│  └───────────────┘    │     AGENT PIPELINE                     │ │
│                       │  Watcher → Analyzer → ContextAgent     │ │
│                       │     ↓                                   │ │
│                       │  BayesianEngine → RiskManager          │ │
│                       │     ↓                                   │ │
│                       │  ExecutionCore → PositionManager        │ │
│                       │     ↓                                   │ │
│                       │  QuantMutator ← BigBrother → Alerts    │ │
│                       └────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ MongoDB  │  │  Redis   │  │  CCXT/Gate   │  │ OpenRouter │  │
│  │  state   │  │  cache   │  │  exchange    │  │    LLM     │  │
│  └──────────┘  └──────────┘  └──────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Agent Roles

| Agent | File | Role |
|---|---|---|
| **WatcherAgent** | `src/watcher.py` | Scans all pairs, ranks by volume + momentum score |
| **AnalyzerAgent** | `src/analyzer.py` | 5-setup multi-TF TA — RSI, MACD, EMA, ATR, OBV |
| **ContextAgent** | `src/context_agent.py` | LLM-powered sentiment, catalyst + risk enrichment |
| **BayesianEngine** | `src/bayesian_engine.py` | Calibrated posterior probability → enter/skip/reject |
| **ExecutionCore** | `src/execution_core.py` | CCXT order placement, limit-first exits, retries |
| **PositionManager** | `src/position_manager.py` | Full lifecycle: tiered exits, trailing, pyramid, time |
| **RiskManager** | `src/risk_manager.py` | Conviction-aware Kelly sizing, drawdown circuit breakers |
| **QuantMutator** | `src/quant_mutator.py` | Self-tunes Bayesian threshold based on win rate + PnL |
| **BigBrother** | `src/bigbrother.py` | Regime detector + supervisor — mode management + alerts |

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
git clone <repo>
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
# → Fill in: GATEIO_API_KEY, GATEIO_API_SECRET, OPENROUTER_API_KEY
```

### Run

```bash
./start_all.sh
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3001 |
| TinyOffice | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |

```bash
./stop_all.sh       # graceful shutdown
```

### Docker (alternative)

```bash
docker compose up -d
```

---

## Configuration

All parameters live in `.env`. The most important sections:

### Exchange
```env
EXCHANGE_NAME=gateio           # gateio | binance | kucoin
EXCHANGE_MODE=paper            # paper | demo | live
GATEIO_API_KEY=...
GATEIO_API_SECRET=...
```

> ⚠️ `INITIAL_EQUITY_USD` is **deprecated** — equity is always fetched live from the exchange at startup. The system refuses to trade until a valid equity value is confirmed.

### Risk & Sizing
```env
MAX_POSITIONS=5
MAX_PORTFOLIO_EXPOSURE_PCT=0.85   # 85% max deployed
MAX_SINGLE_EXPOSURE_PCT=0.15      # 15% per position (hard cap)
MAX_RISK_PER_TRADE_PCT=0.10       # 10% risk per trade
MAX_DRAWDOWN_PCT=0.10
DAILY_LOSS_LIMIT_PCT=0.03
CONSECUTIVE_LOSS_THRESHOLD=3
```

### Exit Rules
```env
STOP_LOSS_PCT=-18.0
TRAILING_STOP_ACTIVATE_PCT=15.0
TRAILING_STOP_DISTANCE_PCT=8.0
TAKE_PROFIT_TIER1_R=2.0         # exit 25% at 2R
TAKE_PROFIT_TIER2_R=5.0         # exit 25% at 5R
TIME_EXIT_HOURS=24.0
```

### Bayesian Thresholds
```env
BAYESIAN_THRESHOLD_NORMAL=0.65
BAYESIAN_THRESHOLD_VOLATILE=0.75
BAYESIAN_THRESHOLD_SAFETY=0.85
```

### LLM (Context Agent)
```env
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=perplexity/sonar-pro
```

See `.env.example` for all ~100 parameters with inline descriptions.

---

## Trading Modes

| Mode | Description |
|---|---|
| `paper` | Simulated fills — zero exchange interaction, zero risk |
| `demo` | Real orders on exchange testnet (Gate.io demo / Binance testnet) |
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
| `GET` | `/api/portfolio` | Live equity, PnL, open positions |
| `GET` | `/api/positions` | Open positions (exchange-sourced) |
| `GET` | `/api/trades` | FIFO-computed realized PnL history |
| `GET` | `/api/performance` | Rolling 7-day metrics |

### Agents & Feed

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/agents` | Per-agent health + metrics |
| `GET` | `/api/feed` | Recent decisions + signals feed |
| `GET` | `/api/regime` | Current detected regime |

### Settings

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/settings` | Current config snapshot |
| `PATCH` | `/api/settings` | Hot-update strategy params |

### Real-Time

| Type | Endpoint | Description |
|---|---|---|
| `WebSocket` | `/ws` | Live swarm state push every cycle |

Interactive docs: **http://localhost:8000/docs**

---

## Project Structure

```
Moonshot-CEX/
├── src/                    # Core agent modules (Python 3.11)
│   ├── config.py           # Pydantic settings — all env vars
│   ├── exchange_ccxt.py    # CCXT async exchange connector
│   ├── watcher.py          # Market scanner
│   ├── analyzer.py         # Multi-TF technical analysis
│   ├── context_agent.py    # LLM sentiment enrichment
│   ├── bayesian_engine.py  # Probabilistic decision engine
│   ├── execution_core.py   # Order placement + limit-first exits
│   ├── position_manager.py # Position lifecycle management
│   ├── risk_manager.py     # Kelly sizing + circuit breakers
│   ├── quant_mutator.py    # Adaptive threshold self-tuning
│   ├── bigbrother.py       # Regime detection + supervisor
│   ├── alerts.py           # Discord / Telegram notifications
│   ├── metrics.py          # Prometheus metric definitions
│   ├── redis_client.py     # Redis cache wrapper
│   └── logger.py           # Loguru configuration
├── backend/
│   └── server.py           # FastAPI orchestrator + all endpoints
├── frontend/               # Next.js 15 dashboard (port 3001)
├── tinyclaw/               # TinyOffice AI chat (port 3000)
├── tests/                  # Pytest test suite
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── start_all.sh
├── stop_all.sh
├── README.md
├── PRODUCT.md
├── TECHNICAL.md
└── ARCHITECTURE.md
```

---

## Observability

| Layer | Tool | URL |
|---|---|---|
| Metrics | Prometheus | http://localhost:8000/metrics |
| API Docs | OpenAPI/Swagger | http://localhost:8000/docs |
| Logs | Loguru → file | `logs/backend.log`, `logs/frontend.log` |
| DB | MongoDB | `positions`, `trades`, `agent_events` collections |
| Cache | Redis | OHLCV, ticker, context caches |
| Alerts | Discord / Telegram | Configured via `.env` |

**Key Prometheus metrics:**  
`account_equity` · `active_positions` · `current_drawdown` · `win_rate` · `decisions_made_total{outcome}` · `signals_generated_total{agent}` · `cycle_duration_seconds`

---

## Tests

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

| Test File | Coverage |
|---|---|
| `tests/test_risk_manager.py` | Conviction sizing, circuit breakers, Kelly |
| `tests/test_bayesian_engine.py` | Posterior calculation, prior updates |
| `tests/test_position_manager.py` | Stop loss, tier exits, close all |
| `tests/test_api.py` | FastAPI endpoint integration |

---

## Safety

- **Never run live without paper + demo testing first**
- API keys need **Spot Trading** only — disable withdrawals
- All secrets in `.env` — never commit to git (`.gitignore` enforced)
- Emergency stop via dashboard button or `POST /api/swarm/emergency-stop`
- Hard circuit breakers: daily loss limit, max drawdown, consecutive loss pause
- Exchange equity fetched and verified before any trade is allowed

---

## Changelog

### v3.0 — March 2026 (Current)

**Exchange-First Data Architecture**
- All financial metrics (equity, PnL, positions) now sourced directly from exchange — MongoDB used for infra only
- FIFO realized PnL calculation (`_compute_pnl_from_fills`) replaces hardcoded zeros
- Unrealized PnL per position shown in real-time from live price feeds
- `INITIAL_EQUITY_USD` deprecated — real equity fetched on startup with 5-retry exponential backoff; swarm blocked until confirmed

**Conviction-Aware Position Sizing** _(biggest change)_
- `compute_position_size()` now accepts `posterior`, `threshold`, `vol_usd`, `ta_score`
- **Conviction multiplier** (0.55× → 1.45×): posterior well above threshold = bigger size; borderline = smaller
- **Liquidity multiplier** (0.45× → 1.00×): 24h vol gates sizing to avoid slippage on illiquid coins
- **TA quality multiplier** (0.90× → 1.10×): higher technical score = modest size boost
- Max single exposure cap (`15%`) always applies regardless of multipliers

**Bayesian Engine Improvements**
- Replaced arbitrary `× 6.5` normalisation with mathematically correct Bayes theorem:  
  `P(H|E) = P(E|H) · P(H) / [P(E|H) · P(H) + P(E|¬H) · P(¬H)]`
- `mean_reversion` prior lowered `0.52 → 0.38` (contrarian setup conflicts with momentum thesis)

**Capital Deployment & Aggressive Momentum Limits (v3.1)**
- `MAX_PORTFOLIO_EXPOSURE_PCT` raised to 95% to ensure full capital utilization
- `MAX_SINGLE_EXPOSURE_PCT` raised to 20% to make bets highly impactful
- `MUTATOR_MIN_SCORE_CEILING` capped at 25 and `ANALYZER_MIN_SCORE` dropped to 15 to ensure the bot continues trading aggressively even in suboptimal regimes
- Modified Pyramiding to compound into winning trades as early as +1.5R (before Tier 1 profit taking)

**Historical NAV Charting & Clean UI**
- Frontend NAV Chart now features Session, 1H, 6H, 1D, 7D interval selection powered by MongoDB snapshots
- Persistent dust-filtering (< $3 USD value) keeps "Ghost" positions off the Open Positions board

### v2.0 — March 2026

- Exchange holdings receive stop loss + trailing stop + time exit protection
- Limit-first exit execution (reprice up to 5× before aggressive limit)
- Symbol cooldown after stop-loss exits (prevents revenge trading)
- FIFO PnL in trade history endpoint

### v1.0 — Initial Release

- Multi-agent swarm: Watcher, Analyzer, Context, Bayesian, Execution, Position, Risk, QuantMutator, BigBrother
- Paper / demo / live mode support
- Gate.io, Binance, KuCoin via CCXT
- Next.js dashboard + TinyOffice chat interface
- MongoDB persistence + Redis caching
- Prometheus metrics + Discord/Telegram alerts
