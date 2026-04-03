# Moonshot-CEX — Technical Architecture Paper

---

## 1. System Overview

Moonshot-CEX is a fully autonomous, multi-agent algorithmic trading system for centralized crypto exchanges. It combines the orchestration model from Moonshot (TinyClaw + TinyOffice + FastAPI + MongoDB) with the exchange intelligence from the AutonomousAIMultiAgentCryptoBot (CCXT + Bayesian Engine + ML TA + Supabase/Redis).

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         MOONSHOT-CEX                             │
│                                                                   │
│  ┌──────────────┐    ┌──────────────────────────────────────┐   │
│  │  TinyOffice   │    │         FastAPI Backend               │   │
│  │  (Next.js)   │◄──►│         (server.py)                  │   │
│  └──────────────┘    │                                      │   │
│                       │  ┌───────────┐  ┌────────────────┐  │   │
│  ┌──────────────┐    │  │  TinyClaw  │  │  Swarm Loop    │  │   │
│  │  Dashboard   │◄──►│  │  Orchestr. │  │  (30s cycle)   │  │   │
│  │  (Next.js)   │    │  └───────────┘  └────────────────┘  │   │
│  └──────────────┘    │                                      │   │
│                       │  AGENT SWARM                         │   │
│                       │  ┌──────────┐  ┌──────────────────┐ │   │
│                       │  │ Watcher  │  │    Analyzer      │ │   │
│                       │  │  Agent   │  │     Agent        │ │   │
│                       │  └──────────┘  └──────────────────┘ │   │
│                       │  ┌──────────┐  ┌──────────────────┐ │   │
│                       │  │ Context  │  │    Bayesian      │ │   │
│                       │  │  Agent   │  │     Engine       │ │   │
│                       │  └──────────┘  └──────────────────┘ │   │
│                       │  ┌──────────┐  ┌──────────────────┐ │   │
│                       │  │Execution │  │    Position      │ │   │
│                       │  │   Core   │  │    Manager       │ │   │
│                       │  └──────────┘  └──────────────────┘ │   │
│                       │  ┌──────────┐  ┌──────────────────┐ │   │
│                       │  │   Risk   │  │     Quant        │ │   │
│                       │  │ Manager  │  │    Mutator       │ │   │
│                       │  └──────────┘  └──────────────────┘ │   │
│                       │  ┌──────────────────────────────┐   │   │
│                       │  │        BigBrother             │   │   │
│                       │  │    (Supervisor + LLM)         │   │   │
│                       │  └──────────────────────────────┘   │   │
│                       └──────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ MongoDB  │  │  Redis   │  │   CCXT   │  │  OpenRouter/   │  │
│  │  (state) │  │ (cache)  │  │(exchange)│  │  Perplexity    │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | Python 3.11+, FastAPI, asyncio | Main server + all agent logic |
| Exchange | CCXT (async) | Binance/Gate.io/KuCoin API |
| Database | MongoDB (Motor async) | Trade history, positions, agent state |
| Cache | Redis | OHLCV cache, context cache, rate limit |
| Frontend | Next.js 15, TypeScript, TailwindCSS | Dashboard |
| AI Chat | TinyOffice (Next.js) | Natural language swarm interface |
| LLM | OpenRouter (Gemini Flash / Perplexity Sonar) | Context enrichment, explanations |
| Metrics | Prometheus + loguru | Observability |
| Alerts | Discord webhook + Telegram Bot | Push notifications |
| Infra | Docker Compose | Containerized deployment |

---

## 3. Agent Architecture

### 3.1 Trading Cycle (30-second cadence)

```
cycle N:
  1. WatcherAgent.scan()          → top 20 candidates by momentum score
  2. AnalyzerAgent.analyze()      → deep TA on 5m/15m/1h/4h per candidate
  3. ContextAgent.enrich()        → LLM sentiment + catalysts per symbol
  4. BayesianEngine.batch_decide()→ posterior probability → enter/skip/reject
  5. RiskManager.can_open()       → portfolio-level gates
  6. ExecutionCore.execute()      → CCXT market/limit order placement
  7. PositionManager.update()     → tick all open positions, check exits
  8. QuantMutator.maybe_mutate()  → self-tune every N cycles
  9. BigBrother.supervise()       → mode management, anomaly detection
 10. broadcast_ws()               → push state to dashboard
```

### 3.2 WatcherAgent

**File:** `src/watcher.py`

Scans all active USDT pairs on the configured exchange. Filters by minimum 24h volume ($2M USD default). For qualifying pairs, fetches 5m OHLCV and computes a composite momentum score:

| Indicator | Weight | Logic |
|-----------|--------|-------|
| RSI (14) | 15 pts | Sweet spot 45–70; penalize overbought >75 |
| MACD histogram | 20 pts | Positive = bullish crossover |
| Volume spike | 20 pts | Current vol / 20-bar avg; capped at 20 pts |
| OBV trend | 15 pts | Slope of OBV over 10 bars (accumulation) |
| Rate of Change | 15 pts | 12-bar RoC; positive momentum |
| EMA alignment | 15 pts | EMA9 > EMA21 > EMA50 = fully aligned |

Outputs top 20 candidates sorted by score (configurable `WATCHER_TOP_N`).

### 3.3 AnalyzerAgent

**File:** `src/analyzer.py`

Multi-timeframe deep TA on watcher candidates across 4 timeframes (5m, 15m, 1h, 4h). Computes:

- **Per timeframe:** RSI, MACD, EMA alignment, volume spike, OBV, rate of change
- **Volatility:** ATR(14), Bollinger Band width
- **Oscillators:** Stochastic RSI (%K, %D)
- **Structure:** Support/resistance from 50-bar pivot points

**Setup Detection:** Classifies each candidate into one of:
- `breakout` — RSI momentum + EMA aligned + volume spike
- `momentum` — RSI 50–70 + positive MACD + OBV accumulation
- `pullback` — Higher TF bullish + lower TF RSI dip to 30–45
- `mean_reversion` — RSI oversold + BB touch + OBV divergence
- `consolidation_breakout` — Tight BB width + volume expansion
- `neutral` — No clear pattern

Outputs `ta_score` (0–100) + `entry_zone` (entry price, stop_loss, take_profit, R:R ratio).

### 3.4 ContextAgent

**File:** `src/context_agent.py`

Uses OpenRouter (Perplexity Sonar Pro by default) to enrich each setup with market intelligence. Batches up to 5 symbols per LLM call to minimize cost. Outputs per symbol:

```json
{
  "sentiment": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "catalysts": ["list of positive drivers"],
  "risks": ["list of risk factors"],
  "driver_type": "narrative|technical|fundamental|whale|unknown",
  "summary": "1-sentence summary"
}
```

**Cache:** 15-minute Redis TTL per symbol. Falls back to neutral context if LLM fails.

### 3.5 BayesianDecisionEngine

**File:** `src/bayesian_engine.py`

Probabilistic decision making combining TA, sentiment, and volume into a posterior probability:

```
P(success | data) ∝ P(data | success) × P(success)

Where:
  P(success) = setup-specific prior (updated online after each trade)
  P(data | success) = ta_likelihood × context_likelihood × vol_likelihood × rr_factor
  
  ta_likelihood   = sigmoid(ta_score, midpoint=65, steepness=0.08)
  context_likelihood = f(sentiment, confidence, narrative_strength)
  vol_likelihood  = sigmoid(vol_spike × 50, midpoint=70, steepness=0.05)
  rr_factor       = min(1.0, 0.5 + R:R_ratio / 6.0)
  
  posterior = prior × combined_likelihood × 6.5  (normalization)
  posterior -= risk_penalty  (0.0–0.30 based on risk count)
```

**Mode thresholds:**
- `normal` → posterior ≥ 0.65
- `volatile` → posterior ≥ 0.75
- `safety` → posterior ≥ 0.85

**Online learning:** After each closed trade, the setup-type prior is updated via exponential smoothing (α=0.05), making the engine continuously learn from outcomes.

### 3.6 ExecutionCore

**File:** `src/execution_core.py`

Handles CEX order placement via CCXT:
- Market buy on entry signal (adjusts amount to exchange precision)
- Limit sell for take profit tiers
- Market sell for stop loss (immediate fill priority)
- Order status polling with retry (max 3 attempts, exponential backoff)
- Tracks fill price, fees, slippage
- Paper mode: simulates fill at current price

### 3.7 PositionManager

**File:** `src/position_manager.py`

Full position lifecycle from open to close:

```
Entry → OPEN
       ↓
   Price ticks + trailing stop management
       ↓
   Tier 1 (2R): sell 25% → PARTIAL
       ↓  
   Tier 2 (5R): sell 25% → PARTIAL
       ↓
   Runner: trailing stop on 50% → CLOSED
       
   OR: Stop loss → CLOSED
   OR: Time exit (max hold hours) → CLOSED
```

**Trailing Stop Logic:**
- Activates when price crosses `trailing_activate_pct` above entry
- Trail distance maintained as percentage below highest price
- Post-tier1 trail tightened by 75% to lock more profit

**Pyramiding:**
- Enabled via `PYRAMID_ENABLED=true`
- Max 2 adds per position
- Requires existing position at ≥ 1.5R profit
- Add size = 50% of original entry size

### 3.8 RiskManager

**File:** `src/risk_manager.py`

Multi-layer portfolio protection:

| Gate | Condition | Action |
|------|-----------|--------|
| Max positions | Open count ≥ `MAX_POSITIONS` (5) | Block new entries |
| Max exposure | Portfolio exposure ≥ 30% | Block new entries |
| Daily loss | Day PnL ≤ -3% equity | Block new entries for 24h |
| Drawdown | Drawdown ≥ 10% | Switch to safety mode |
| Consecutive losses | 3 consecutive losses | 10-minute pause |
| Correlation | New pair correlation > 0.7 with existing | Block (avoid duplicate exposure) |

**Position Sizing (Half-Kelly):**
```
kelly_fraction = win_rate - (1 - win_rate) / avg_win_loss_ratio
position_size = (kelly_fraction × 0.5) × equity  (half-Kelly)
capped at: MAX_SINGLE_EXPOSURE_PCT × equity
```

Uses rolling 90-day trade history from MongoDB. Falls back to `MAX_RISK_PER_TRADE_PCT` (1% default) when < 30 trades available.

### 3.9 QuantMutator

**File:** `src/quant_mutator.py`

Self-adaptive strategy tuning every `QUANT_MUTATOR_EVERY_N_CYCLES` (default: 5) cycles:

**Win Rate → Confidence Threshold:**
- Win rate > 65% (hot streak) → lower `min_confidence` by 3 pts (more trades)
- Win rate < 40% (cold streak) → raise `min_confidence` by 5 pts (fewer trades)
- PnL < -5% today → emergency raise of `min_confidence` + 10 pts

**Volume Filter:**
- Chain-level high win rate → slightly lower volume requirements
- Chain-level low win rate → raise volume bar

**Persistence:** All mutations logged to MongoDB with before/after values for audit.

### 3.10 BigBrother

**File:** `src/bigbrother.py`

The supervisor that watches everything:

**Regime Detection:**
```python
regime = detect_regime(btc_24h_change, btc_volume_ratio, recent_win_rate)

bull:     btc_24h > +3% AND volume_ratio > 1.2 AND win_rate > 0.55
bear:     btc_24h < -3% AND volume_ratio > 1.5 (fear) AND win_rate < 0.40
sideways: everything else
```

**Regime × Exit Parameters:**
```
                   SL      Trail     TP1    TP2    Time
bull:             -22%   12%/9%    80%   300%    5h
sideways:         -18%   15%/8%    60%   200%    3h
bear:             -12%   20%/6%    35%   80%     1.5h
```

**Mode Switching:**
- Drawdown > 10% → `safety` mode (higher Bayesian threshold)
- Daily loss > 3% → pause mode (no new entries)
- Win rate < 35% rolling 20 trades → `volatile` mode
- Recovery sustained 3+ cycles → return to `normal`

---

## 4. Exchange Layer (CCXT)

**File:** `src/exchange_ccxt.py`

```python
class ExchangeConnector:
    exchanges: ["gateio", "binance", "kucoin"]
    modes: ["paper", "demo", "live"]
    
    features:
    - enableRateLimit: True (CCXT built-in)
    - Retry: 3 attempts, exponential backoff
    - Demo mode: Binance Demo API / Gate.io Testnet
    - Market precision rounding (amount_to_precision, price_to_precision)
    - Spot markets only (no futures/margin)

class MultiExchangeManager:
    - Primary + fallback exchange routing
    - Automatic failover on exchange errors
```

**Exchange API Endpoints Used:**
- `fetch_tickers()` → scan all pairs
- `fetch_ohlcv()` → candle data for TA
- `fetch_order_book()` → liquidity depth
- `fetch_balance()` → account equity
- `create_order()` → market/limit orders
- `fetch_order()` → order status polling
- `cancel_order()` → cancel stale limit orders

---

## 5. Data Flow & Persistence

### MongoDB Collections

| Collection | Contents | TTL |
|-----------|---------|-----|
| `positions` | Open/closed positions with full trade history | Forever |
| `trades` | Individual buy/sell fills | Forever |
| `watcher_signals` | Per-cycle scanner outputs | 30 days |
| `analyzer_setups` | TA setups + entry zones | 30 days |
| `context_analyses` | LLM context per symbol | 24h |
| `bayesian_decisions` | Every enter/skip/reject + reasoning | 30 days |
| `agent_events` | BigBrother events, mode changes | 90 days |
| `performance_metrics` | Daily PnL, win rate, equity | Forever |
| `quant_mutations` | Strategy parameter history | Forever |

### Redis Cache Keys

| Key | Contents | TTL |
|-----|---------|-----|
| `ohlcv:{symbol}:{tf}` | OHLCV candle array | 4 min |
| `ticker:{symbol}` | Latest ticker | 30s |
| `context:{symbol}` | LLM context | 15 min |
| `watcher:{symbol}` | Watcher candidate | 5 min |
| `regime:current` | Detected regime | 5 min |

---

## 6. API Endpoints (FastAPI)

### Swarm Control
| Method | Endpoint | Description |
|--------|---------|-------------|
| POST | `/api/swarm/start` | Start the trading swarm |
| POST | `/api/swarm/stop` | Stop the trading swarm gracefully |
| POST | `/api/swarm/emergency-stop` | Immediately close all positions + stop |
| GET | `/api/swarm/status` | Current swarm status + agent metrics |
| GET | `/api/swarm/autopilot` | DRY_RUN status + mode |

### Portfolio
| Method | Endpoint | Description |
|--------|---------|-------------|
| GET | `/api/portfolio` | Full portfolio snapshot |
| GET | `/api/positions` | Open positions |
| GET | `/api/trades` | Recent trade history |
| GET | `/api/performance` | 7-day rolling metrics |

### Agent Feeds
| Method | Endpoint | Description |
|--------|---------|-------------|
| GET | `/api/agents` | All agent metrics |
| GET | `/api/feed` | Neural feed (recent decisions/signals) |
| GET | `/api/regime` | Current detected regime |

### TinyClaw (Orchestrator)
| Method | Endpoint | Description |
|--------|---------|-------------|
| POST | `/api/tc/api/message` | Send command/question to swarm |
| GET | `/api/tc/agents` | TinyClaw agent list |
| GET | `/api/tc/stream` | SSE stream for real-time responses |

### Settings
| Method | Endpoint | Description |
|--------|---------|-------------|
| GET | `/api/settings` | Current config (public values) |
| PATCH | `/api/settings` | Hot-update strategy parameters |

### WebSocket
| Endpoint | Description |
|---------|-------------|
| `/ws` | Real-time swarm state push (cycle updates) |

---

## 7. TinyClaw / TinyOffice Integration

TinyClaw is the AI orchestration layer sitting between TinyOffice (chat UI) and the trading swarm:

```
User (TinyOffice) → POST /api/tc/api/message
                  → TinyClaw processes intent
                  → Calls relevant swarm endpoints or MongoDB
                  → Returns explanation via OpenRouter LLM
                  → SSE stream for long-running responses
```

**Supported TinyClaw Commands:**
- "Why did you buy ETH?" → Queries last ETH trade + Bayesian reasoning + context
- "What's the current regime?" → BigBrother regime + explanation
- "Pause trading" → Sets swarm pause flag
- "Show me today's PnL" → MongoDB aggregate + formatted response
- "What's your win rate?" → Performance tracker summary
- "Switch to safety mode" → Force BigBrother mode change

---

## 8. Configuration Reference

All parameters externalized to `.env`. Key sections:

```bash
# ── Exchange ──────────────────────────────────────────────────
EXCHANGE_NAME=gateio            # gateio | binance | kucoin
EXCHANGE_MODE=paper             # paper | demo | live

# ── Watcher ──────────────────────────────────────────────────
WATCHER_MIN_VOLUME_24H_USD=2000000
WATCHER_TOP_N=20

# ── Analyzer ─────────────────────────────────────────────────
ANALYZER_MIN_SCORE=30.0
ANALYZER_TOP_N=5
ANALYZER_TIMEFRAMES=5m,15m,1h,4h

# ── Risk Management ──────────────────────────────────────────
MAX_POSITIONS=5
MAX_PORTFOLIO_EXPOSURE_PCT=0.30
MAX_RISK_PER_TRADE_PCT=0.01
MAX_DRAWDOWN_PCT=0.10
DAILY_LOSS_LIMIT_PCT=0.03
CONSECUTIVE_LOSS_THRESHOLD=3
CONSECUTIVE_LOSS_PAUSE_MINUTES=10

# ── Exit Rules ───────────────────────────────────────────────
STOP_LOSS_PCT=-18.0
TRAILING_STOP_ACTIVATE_PCT=15.0
TRAILING_STOP_DISTANCE_PCT=8.0
TAKE_PROFIT_TIER1_R=2.0         # exit 25% at 2R
TAKE_PROFIT_TIER2_R=5.0         # exit 25% at 5R
TIME_EXIT_HOURS=4.0

# ── Bayesian ─────────────────────────────────────────────────
BAYESIAN_THRESHOLD_NORMAL=0.65
BAYESIAN_THRESHOLD_VOLATILE=0.75
BAYESIAN_THRESHOLD_SAFETY=0.85

# ── Regime ───────────────────────────────────────────────────
REGIME_BULL_THRESHOLD=3.0       # BTC 24h change % above = bull
REGIME_BEAR_THRESHOLD=-3.0      # BTC 24h change % below = bear
```

---

## 9. Deployment

### Docker Compose Services

```yaml
services:
  backend:    # FastAPI server + all agents
  frontend:   # Next.js dashboard (port 3000)
  tinyoffice: # TinyOffice AI chat (port 3001)
  mongodb:    # MongoDB 6 (port 27017)
  redis:      # Redis 7 (port 6379)
  prometheus: # Metrics scraping (port 9090)
```

### Resource Requirements

| Component | CPU | RAM | Storage |
|-----------|-----|-----|---------|
| Backend | 0.5 core | 512MB | 100MB |
| Frontend | 0.25 core | 256MB | 50MB |
| MongoDB | 0.5 core | 1GB | 10GB |
| Redis | 0.1 core | 128MB | 100MB |
| **Total** | **~1.5 cores** | **~2GB** | **~11GB** |

Runs comfortably on a $6/month VPS (2 vCPU, 4GB RAM).

---

## 10. Security Considerations

- **API Keys:** Never stored in code; loaded from `.env` at runtime
- **Exchange permissions:** Set API keys to **Spot Trading + Read Only** — no withdrawal permissions
- **MongoDB auth:** Enable in production via `MONGO_URL=mongodb://user:pass@localhost`
- **Redis auth:** Set `REDIS_PASSWORD` in production
- **TinyOffice:** Runs on localhost by default; add auth layer if exposing publicly
- **CORS:** Restricted to localhost in production config
- **Rate limiting:** All exchange calls go through CCXT rate limiter + retry backoff

---

## 11. Testing Strategy

| Test Type | Location | Coverage |
|-----------|---------|---------|
| Unit | `tests/test_agents.py` | WatcherAgent, AnalyzerAgent, BayesianEngine, RiskManager |
| Integration | `tests/test_integration.py` | Full cycle with mock exchange |
| Exchange | `tests/test_exchange.py` | CCXT connector, paper fill logic |
| Performance | `tests/test_performance_tracker.py` | Metrics calculation |
| E2E | `tests/test_e2e.py` | Full paper-mode trading cycle |

Run: `pytest tests/ -v --timeout=30`

---

## 12. Observability

**Prometheus Metrics:**
- `cycle_duration_seconds` — Trading cycle latency
- `signals_generated_total{agent}` — Signals per agent
- `decisions_made_total{outcome}` — enter/skip/reject counts
- `active_positions` — Current open position count
- `account_equity` — Portfolio value in USDT
- `current_drawdown` — Drawdown from peak
- `win_rate` — Rolling win rate
- `api_latency_seconds{exchange, endpoint}` — Exchange API latency
- `errors_total{component, error_type}` — Error counts

**Log Levels:**
- `INFO` — Trade entries/exits, cycle summaries, mode changes
- `WARNING` — Risk gates triggered, retry attempts, rate limits
- `ERROR` — Exchange failures, LLM failures, unexpected exceptions
- `DEBUG` — Per-symbol scoring, indicator values (verbose mode)

---

## 15. Recent Changes (v3.1) — Regime-Adaptive Strategy

### 15.1 4-Regime Detection System

**Problem:** System previously treated "sideways" and "choppy" identically. Choppy markets (high volatility, no direction) are the most destructive regime for momentum bots — whipsaws cause repeated small losses.

**Solution:** Added dedicated `choppy` regime with separate detection logic:
```python
# Choppy override — triggers when 2+ of these are true:
if recent_wr < 0.42:        choppy_signals += 1   # poor win rate
if avg_hold_h < 0.75:       choppy_signals += 1   # < 45 min avg hold (whipsaws)
if -1.5 < btc_change < 1.5: choppy_signals += 1   # BTC tight range
if choppy_signals >= 2:     return "choppy"
```

**Files modified:** `src/bigbrother.py`

### 15.2 Per-Regime Capital Deployment Tables

**Problem:** Prior system had a single `MAX_PORTFOLIO_EXPOSURE_PCT` and fixed position multiplier regardless of regime. Bear and choppy markets had same capital deployment as bull.

**Solution:** Per-regime capital tables:

| Regime | Max Exposure | Size Multiplier | Max Positions | Bayesian Threshold |
|---|---|---|---|---|
| bull | 85% | 1.00× | 5 | 0.60 |
| sideways | 65% | 0.85× | 4 | 0.65 (default) |
| bear | 40% | 0.60× | 3 | 0.75 |
| choppy | 25% | 0.45× | 2 | 0.82 |

**Files modified:** `src/bigbrother.py`, `backend/server.py`

### 15.3 Setup Allowlist by Regime

**Problem:** In bear and choppy regimes, momentum, pullback, and mean_reversion setups have extremely low hit rates — they conflict with the market structure.

**Solution:** Per-regime setup allowlists enforced before risk gates:
- `bull` / `sideways`: all setups allowed
- `bear`: only `breakout`
- `choppy`: only `breakout` with ta_score ≥ 75

**Files modified:** `src/bigbrother.py`, `backend/server.py`

### 15.4 Account-Size Tier Detection

**Problem:** A $1K account and $50K account had identical Kelly fractions and max_positions — the $1K account was mathematically over-diversified, each position representing a dangerous fraction of equity.

**Solution:** Tier detection at startup from live equity:

| Tier | Equity | Kelly Multiplier | Max Positions | Max Single | Risk/Trade |
|---|---|---|---|---|---|
| small | < $2K | 0.25× | 2–3 | 10% | 1–2% |
| medium | $2K–$20K | 0.50× | 4–6 | 15% | 3–5% |
| large | > $20K | 0.60× | 6–10 | 15% | 5–8% |

**Files modified:** `src/risk_manager.py`, `backend/server.py`

### 15.5 Drawdown-Gradient Sizing

**Problem:** Prior system was binary: normal sizing until drawdown hit 10% (safety mode). No pre-emptive de-risking between 0–10%.

**Solution:** Gradient size reduction:

| Drawdown | Size Multiplier |
|---|---|
| 0–3% | 1.00× (full size) |
| 3–5% | 0.80× (pre-emptive caution) |
| 5–10% | 0.60× (safety mode range) |
| 10–15% | 0.40× (deep safety) |
| > 15% | 0.00× (full halt in `can_open_position`) |

**Files modified:** `src/risk_manager.py`

### 15.6 Win-Streak Size Bonus

**Problem:** System had consecutive-loss protection but no win-streak reward — capital underdeployed during hot streaks.

**Solution:**
- 3+ consecutive wins → +15% size bonus
- 5+ consecutive wins → +25% size bonus (cap)
- **Regime-gated:** only active in `bull` or `sideways` — no streak bonus in bear/choppy

**Files modified:** `src/risk_manager.py`

### 15.7 Aggressive Momentum Limits & Pyramiding Logic

**Problem:** The bot was severely underutilizing capital due to stringent Bayesian/Mutator thresholds and flawed pyramiding gate logic (pyramid triggered only after Tier 1). 
**Solution:**
- Lowered `.env` caps (`MUTATOR_MIN_SCORE_CEILING=25`, `ANALYZER_MIN_SCORE=15`, `BAYESIAN_THRESHOLD_NORMAL=0.10`) to massively increase trading frequency.
- Raised `MAX_PORTFOLIO_EXPOSURE_PCT=0.95` and `MAX_SINGLE_EXPOSURE_PCT=0.20`.
- Modified `PositionManager._check_exits` to trigger pyramiding at `pyramid_min_r` (default 1.5R) independently of Tier 1 profit taking.

**Files modified:** `.env`, `src/position_manager.py`

### 15.8 Dust Filtering & Historical NAV Charting

**Problem:** Tiny remainders on the exchange appeared as "Ghost" positions in the UI. The NAV chart lacked historical lookback.
**Solution:**
- `_get_exchange_account_snapshot` applies a hard < $3 USD filter dropping dust logic.
- Implemented `/api/equity/history?since=...` hitting MongoDB directly for Session, 1H, 6H, 1D, 7D intervals parsed natively in the frontend `NavChart.tsx`.

**Files modified:** `backend/server.py`, `frontend/src/components/NavChart.tsx`

---

## 16. Future Enhancements

| Priority | Enhancement | Expected Impact |
|---|---|---|
| �� High | **Volatility-parity sizing** — size by equal dollar risk via ATR | Equal risk exposure; better Sharpe |
| 🔴 High | **LSTM price forecaster** — directional probability as Bayesian input | +12.8% ROI (2025 research) |
| 🟠 Medium | **On-chain metrics fusion** — active addresses, exchange inflows | +15–30% signal accuracy |
| 🟠 Medium | **Dynamic time exit by regime** — 48h bull / 12h sideways / 8h bear | Less opportunity cost |
| 🟠 Medium | **Shorting in bear regime** (margin account) — 50% of long size | +10–20% in bear markets |
| �� Low | **TWAP order splitting** — large entries over 2–3 ticks | −20% slippage |
| 🟡 Low | **Market-cap tiering** — lower max exposure for small caps | Reduces blow-up risk |
