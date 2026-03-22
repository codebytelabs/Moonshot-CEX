# Moonshot-CEX Trading Bot Architecture

**Version:** 2.0  
**Last Updated:** March 18, 2026  
**Exchange:** Gate.io (Demo/Live modes supported)  
**Asset Class:** Cryptocurrency spot trading (CEX)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Core Agents](#core-agents)
4. [Trading Strategy](#trading-strategy)
5. [Exit Strategy](#exit-strategy)
6. [Risk Management](#risk-management)
7. [Execution Flow](#execution-flow)
8. [Data Flow](#data-flow)
9. [Configuration](#configuration)
10. [Deployment](#deployment)
11. [Monitoring & Observability](#monitoring--observability)

---

## System Overview

Moonshot-CEX is a **fully autonomous multi-agent trading system** designed for cryptocurrency spot trading on centralized exchanges. The system operates in a continuous cycle, scanning markets, analyzing opportunities, filtering signals through Bayesian inference, managing risk, executing trades, and monitoring positions.

### Key Characteristics

- **Fully Autonomous**: Operates 24/7 without human intervention once started
- **Multi-Agent Architecture**: Specialized agents handle distinct responsibilities
- **Adaptive Strategy**: Regime-aware parameters adjust to market conditions
- **Professional Execution**: Limit-first order placement with intelligent repricing
- **Comprehensive Risk Management**: Position sizing, exposure limits, stop losses, trailing stops
- **Real-time Monitoring**: WebSocket-based dashboard with live updates

### Operational Modes

1. **Paper Mode**: Simulated trading with no real exchange interaction
2. **Demo Mode**: Real exchange interaction using testnet/demo accounts
3. **Live Mode**: Production trading with real capital

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Dashboard   │  │  TinyOffice  │  │   Metrics    │         │
│  │ (Next.js)    │  │   (Chat)     │  │ (Prometheus) │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                  │                  │                  │
│         └──────────────────┼──────────────────┘                  │
│                            │                                     │
└────────────────────────────┼─────────────────────────────────────┘
                             │ WebSocket/HTTP
┌────────────────────────────┼─────────────────────────────────────┐
│                         BACKEND LAYER                            │
│                    (FastAPI + AsyncIO)                           │
│                            │                                     │
│  ┌─────────────────────────┴──────────────────────────┐         │
│  │              TRADING CYCLE ORCHESTRATOR             │         │
│  │         (15-second continuous loop)                 │         │
│  └─────────────────────────┬──────────────────────────┘         │
│                            │                                     │
│  ┌─────────────────────────┴──────────────────────────┐         │
│  │                  AGENT PIPELINE                     │         │
│  │                                                     │         │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │         │
│  │  │ Watcher  │→ │ Analyzer │→ │ Context  │         │         │
│  │  │  Agent   │  │  Agent   │  │  Agent   │         │         │
│  │  └──────────┘  └──────────┘  └──────────┘         │         │
│  │       ↓              ↓              ↓              │         │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │         │
│  │  │ Bayesian │→ │   Risk   │→ │Execution │         │         │
│  │  │  Filter  │  │ Manager  │  │   Core   │         │         │
│  │  └──────────┘  └──────────┘  └──────────┘         │         │
│  │       ↓              ↓              ↓              │         │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │         │
│  │  │Position  │  │BigBrother│  │  Quant   │         │         │
│  │  │ Manager  │  │Supervisor│  │ Mutator  │         │         │
│  │  └──────────┘  └──────────┘  └──────────┘         │         │
│  │                                                     │         │
│  └─────────────────────────────────────────────────────┘         │
│                            │                                     │
└────────────────────────────┼─────────────────────────────────────┘
                             │
┌────────────────────────────┼─────────────────────────────────────┐
│                      DATA & EXCHANGE LAYER                       │
│                            │                                     │
│  ┌──────────┐  ┌──────────┴───────┐  ┌──────────┐              │
│  │ MongoDB  │  │  Exchange (CCXT) │  │  Redis   │              │
│  │  (Trades │  │   Gate.io API    │  │ (Cache)  │              │
│  │   & DB)  │  │                  │  │          │              │
│  └──────────┘  └──────────────────┘  └──────────┘              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Core Agents

### 1. Watcher Agent

**Purpose**: Market scanner that identifies potential trading opportunities

**Responsibilities**:
- Scans configured trading pairs (default: 36 pairs)
- Fetches OHLCV data from Redis cache or exchange API
- Calculates initial technical indicators (RSI, volume ratio, price change)
- Scores candidates based on momentum, volume, and volatility
- Filters out low-quality candidates early

**Output**: List of candidate symbols with preliminary scores

**Key Metrics**:
- Scan frequency: Every 15 seconds
- Pairs monitored: 36 (configurable)
- Cache hit rate: ~95% (Redis OHLCV caching)

**Configuration**:
```env
WATCHER_MIN_SCORE=20.0
WATCHER_MIN_VOL_5M=300.0
WATCHER_TOP_N_AUDIT=8
```

---

### 2. Analyzer Agent

**Purpose**: Deep technical analysis and setup identification

**Responsibilities**:
- Performs multi-timeframe analysis (5m, 15m, 1h, 4h)
- Identifies chart patterns and setups:
  - Breakout
  - Momentum
  - Pullback
  - Mean reversion
  - Consolidation breakout
  - Neutral (no clear pattern)
- Calculates entry zones with stop loss and take profit levels
- Computes risk/reward ratios
- Generates composite TA scores

**Output**: List of trading setups with entry/exit parameters

**Key Metrics**:
- Analysis time: ~0.5s per batch
- Setups generated: 10-12 per cycle
- Min TA score: 15.0 (configurable)

**Technical Indicators Used**:
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- EMA alignment (trend confirmation)
- ATR (Average True Range) for volatility
- Support/resistance levels
- Volume profile

**Configuration**:
```env
ANALYZER_MIN_SCORE=15.0
TIER1_R_MULTIPLE=2.0
TIER2_R_MULTIPLE=5.0
```

---

### 3. Context Agent

**Purpose**: Enriches setups with fundamental and sentiment data

**Responsibilities**:
- Fetches news and social sentiment (optional, can be disabled)
- Identifies catalysts (partnerships, launches, upgrades)
- Identifies risks (regulatory, technical, market)
- Assigns sentiment scores (bullish/bearish/neutral)
- Provides context likelihood for Bayesian filter

**Output**: Enriched setups with context metadata

**Status**: Currently disabled (neutral context used as baseline)

**Configuration**:
```env
CONTEXT_ENABLED=false
CONTEXT_MODEL=perplexity/sonar-pro-search
```

---

### 4. Bayesian Filter

**Purpose**: Probabilistic decision-making using Bayesian inference

**Responsibilities**:
- Applies prior probabilities based on setup type
- Calculates likelihoods from TA score, context, volume, and R/R ratio
- Computes posterior probability for each setup
- Filters setups below confidence threshold
- Adapts priors based on historical win rates

**Output**: Approved setups with posterior probabilities

**Decision Formula**:
```
posterior = (prior × ta_likelihood × ctx_likelihood × vol_likelihood × rr_factor) / normalization
```

**Priors by Setup Type**:
- Breakout: 0.62
- Momentum: 0.58
- Pullback: 0.55
- Mean reversion: 0.52
- Consolidation breakout: 0.60
- Neutral: 0.45

**Configuration**:
```env
BAYESIAN_THRESHOLD=0.22
BAYESIAN_MODE=normal
```

---

### 5. Risk Manager

**Purpose**: Portfolio-level risk control and position sizing

**Responsibilities**:
- Enforces maximum position count (10 positions)
- Enforces maximum exposure (90% of equity)
- Prevents duplicate symbol entries
- Calculates position size based on:
  - Account equity
  - Stop loss distance
  - Risk per trade (2% of equity)
  - Maximum single exposure (15%)
- Tracks win rate, R-multiples, and consecutive losses
- Implements circuit breakers (pauses after 3 consecutive losses)

**Output**: Position size in USD for approved entries

**Risk Parameters**:
```env
MAX_POSITIONS=10
MAX_TOTAL_EXPOSURE_PCT=90.0
MAX_SINGLE_EXPOSURE_PCT=15.0
RISK_PER_TRADE_PCT=2.0
```

**Position Sizing Formula**:
```python
risk_amount = equity × risk_per_trade_pct
position_size = risk_amount / stop_loss_distance
position_size = min(position_size, equity × max_single_exposure_pct)
```

---

### 6. Execution Core

**Purpose**: Order placement and execution with professional limit-first strategy

**Responsibilities**:
- **Entry**: Market buy orders with retry logic
- **Exit**: Limit-first sell orders with intelligent repricing
  - Initial limit order at +8 bps above best ask
  - Poll order status every 3 seconds
  - Cancel and reprice if not filled (-6 bps per attempt)
  - Final attempt at -2 bps (aggressive limit, not market)
- Handles partial fills correctly
- Fetches actual exchange balances before selling
- Simulates fills in paper mode

**Output**: Order fill data with prices, amounts, fees

**Execution Modes**:
- **Paper**: Simulated fills with 0.1% slippage
- **Demo**: Real testnet orders
- **Live**: Production orders

**Configuration**:
```env
EXCHANGE_MODE=demo
MAX_SELL_RETRIES=5
EXIT_LIMIT_POLL_SECONDS=3
EXIT_LIMIT_INITIAL_MARKUP_BPS=8
EXIT_LIMIT_REPRICE_STEP_BPS=6
EXIT_LIMIT_FINAL_CROSS_BPS=2
```

**Why Limit-First Exits?**:
- Reduces slippage vs market orders
- Captures better prices during volatility
- More professional execution
- Still falls back to aggressive limit if needed

---

### 7. Position Manager

**Purpose**: Position lifecycle management and exit orchestration

**Responsibilities**:
- Opens new positions with entry data
- Tracks position state (amount, PnL, highest price, trailing stop)
- Evaluates exit conditions every cycle:
  - **Stop loss**: Hard floor at configured % (default -10%)
  - **Trailing stop**: Activates at +5%, trails at 3.5% distance
  - **Momentum exits**: Staged reviews at 5m, 10m, 15m, 20m intervals
  - **Time exit**: Closes positions after 1.5 hours (regime-aware)
  - **Tier exits**: Partial exits at 2R and 5R
- Handles partial fills without closing full position
- Maintains closed trade history

**Output**: Exit events with PnL and close reasons

**Exit Conditions** (in priority order):

1. **Stop Loss** (always applies)
   - Triggers if price ≤ stop_loss OR pnl_pct ≤ -10%

2. **Trailing Stop** (always applies)
   - Activates when PnL ≥ +5%
   - Trails 3.5% below highest price
   - Tightens to 2.6% after Tier 1 exit

3. **Momentum Exits** (bot trades only, staged):
   - `no_traction_5m`: After 5m if peak < 0.4% and pnl ≤ -0.35%
   - `momentum_died_10m`: After 10m if peak < 0.8% and pnl ≤ 0%
   - `momentum_died_15m`: After 15m if peak < 1.2% and pnl < 0.3%
   - `momentum_died_20m`: After 20m if peak < 2.0% and pnl < 0.5%
   - `momentum_faded`: If had real run-up but gave back 60%+ of peak

4. **Time Exit** (all positions)
   - Closes after 1.5 hours (regime-aware, adjusts in bull/bear)

5. **Tier Exits** (partial exits):
   - Tier 1: Sell 50% at 2R (2× risk multiple)
   - Tier 2: Sell 30% at 5R (5× risk multiple)

**Configuration**:
```env
STOP_LOSS_PCT=-10.0
TRAILING_STOP_ACTIVATE_PCT=5.0
TRAILING_STOP_DISTANCE_PCT=3.5
TIME_EXIT_HOURS=1.5
MOMENTUM_RECHECK_INTERVAL_MINUTES=5
TIER1_EXIT_PCT=0.5
TIER2_EXIT_PCT=0.3
```

**Exchange Holdings Protection**:
- As of v2.0, exchange holdings now receive:
  - Dynamic stop loss at configured %
  - Time exit after configured hours
  - Trailing stop if they run up
- Previously, exchange holdings had no exit protection (bug fixed)

---

### 8. BigBrother Supervisor

**Purpose**: Regime detection and adaptive parameter management

**Responsibilities**:
- Detects market regime (bull/sideways/bear) based on:
  - Win rate trends
  - Drawdown levels
  - Consecutive losses
  - Average R-multiples
- Adjusts strategy parameters by regime:
  - **Bull**: Wider stops, higher TPs, longer hold times
  - **Sideways**: Balanced parameters
  - **Bear**: Tighter stops, lower TPs, faster exits
- Manages operating modes (normal/cautious/aggressive)
- Implements emergency stop if drawdown > 15%
- Tracks portfolio health metrics

**Output**: Regime parameters and operating mode

**Regime Parameters**:

| Regime    | Stop Loss | Trail Activate | Trail Distance | TP1  | TP2  | Time Exit |
|-----------|-----------|----------------|----------------|------|------|-----------|
| Bull      | -22%      | 12%            | 9%             | 80%  | 300% | 5h        |
| Sideways  | -18%      | 15%            | 8%             | 60%  | 200% | 3h        |
| Bear      | -12%      | 20%            | 6%             | 35%  | 80%  | 1.5h      |

**Configuration**:
```env
BIGBROTHER_MODE=normal
EMERGENCY_STOP_DRAWDOWN_PCT=15.0
```

---

### 9. Quant Mutator

**Purpose**: Dynamic parameter optimization based on performance

**Responsibilities**:
- Adjusts Bayesian threshold based on win rate
- Adjusts analyzer min_score based on setup quality
- Implements adaptive learning from trade outcomes
- Prevents over-optimization (bounded adjustments)

**Output**: Updated min_score and threshold values

**Adjustment Logic**:
- If win_rate > 60%: Lower threshold (enter more)
- If win_rate < 40%: Raise threshold (enter less)
- If avg_r_multiple > 2.0: Lower min_score (accept more setups)
- If avg_r_multiple < 1.0: Raise min_score (be more selective)

**Configuration**:
```env
QUANT_MUTATOR_ENABLED=true
```

---

## Trading Strategy

### Strategy Philosophy

**Momentum Hunting with Adaptive Exits**

The bot is designed to:
1. **Catch early momentum** in trending assets
2. **Exit quickly** if momentum doesn't materialize
3. **Let winners run** with trailing stops
4. **Cut losses fast** with tight stop losses

This is **not** a buy-and-hold strategy. It's a short-term momentum trading system optimized for 15-minute to 2-hour hold times.

### Entry Criteria

A position is opened when **all** of the following are true:

1. **Watcher**: Symbol passes initial scan (score > 20, volume > 300)
2. **Analyzer**: Setup identified with TA score > 15
3. **Bayesian**: Posterior probability > 0.22 (22% confidence)
4. **Risk Manager**: 
   - Open positions < 10
   - Total exposure < 90%
   - Symbol not already held
   - Position size calculable within limits
5. **Execution**: Order successfully filled on exchange

### Setup Types

1. **Breakout**: Price breaking above resistance with volume
2. **Momentum**: Strong directional move with aligned EMAs
3. **Pullback**: Retracement in uptrend to support
4. **Mean Reversion**: Oversold bounce from support
5. **Consolidation Breakout**: Range breakout after consolidation
6. **Neutral**: No clear pattern but meets minimum criteria

### Position Sizing

```python
# Risk-based sizing
risk_amount = equity × 2%
position_size = risk_amount / stop_loss_distance

# Capped by exposure limits
position_size = min(position_size, equity × 15%)
```

**Example**:
- Equity: $10,000
- Risk per trade: 2% = $200
- Stop loss distance: 5% = $0.05 per $1
- Position size: $200 / 0.05 = $4,000
- Max single exposure: $10,000 × 15% = $1,500
- **Final position size: $1,500** (capped by exposure limit)

---

## Exit Strategy

### Exit Philosophy

**Adaptive, Multi-Layered, Momentum-Aware**

The exit strategy is the most sophisticated part of the system. It uses **staged momentum reviews** instead of a single time-based exit, allowing winners to run while cutting losers quickly.

### Exit Layers (Priority Order)

#### 1. Hard Stop Loss (Always Active)
- Triggers: `price ≤ stop_loss` OR `pnl_pct ≤ -10%`
- Purpose: Absolute loss protection
- Applies to: All positions (bot + exchange holdings)

#### 2. Trailing Stop (Always Active)
- Activation: When PnL ≥ +5%
- Distance: 3.5% below highest price
- Tightening: Reduces to 2.6% after Tier 1 exit
- Purpose: Lock in profits on winners
- Applies to: All positions (bot + exchange holdings)

#### 3. Staged Momentum Exits (Bot Trades Only)

Instead of a single 15-minute cutoff, the bot now **re-evaluates momentum every 5 minutes**:

**5-Minute Check** (`no_traction_5m`):
- Condition: Peak PnL < 0.4% AND current PnL ≤ -0.35%
- Reasoning: Position immediately went against us, no traction

**10-Minute Check** (`momentum_died_10m`):
- Condition: Peak PnL < 0.8% AND current PnL ≤ 0% AND near entry
- Reasoning: Minimal movement in 10 minutes, momentum never materialized

**15-Minute Check** (`momentum_died_15m`):
- Condition: Peak PnL < 1.2% AND current PnL < 0.3% AND near entry
- Reasoning: Still no meaningful momentum after 15 minutes

**20-Minute Check** (`momentum_died_20m`):
- Condition: Peak PnL < 2.0% AND current PnL < 0.5%
- Reasoning: 20 minutes with minimal progress, cut it

**Fade Detection** (`momentum_faded`):
- Condition: Had real run-up (peak ≥ 1.0%) but gave back 60%+ of peak
- Reasoning: Momentum clearly reversed, exit before it bleeds more

**Key Insight**: A position that runs to +3% in 10 minutes will **not** be cut at 15 minutes. Only positions that truly stalled get exited.

#### 4. Time Exit (All Positions)
- Default: 1.5 hours
- Regime-aware: Adjusts to 5h (bull), 3h (sideways), 1.5h (bear)
- Purpose: Don't hold dead money indefinitely
- Applies to: All positions (bot + exchange holdings)
- **New in v2.0**: Now applies to exchange holdings too

#### 5. Tier Exits (Partial Exits)

**Tier 1** (50% exit at 2R):
- Condition: R-multiple ≥ 2.0
- Action: Sell 50% of position
- Effect: Lock in 1R profit, let 50% run risk-free
- Trailing stop tightens to 2.6% after this

**Tier 2** (30% exit at 5R):
- Condition: R-multiple ≥ 5.0
- Action: Sell 30% of remaining position
- Effect: Lock in additional profit, keep 20% for moonshot

**Example**:
- Entry: $1,000 position at $100, stop at $95 (R = $5)
- At $110 (2R): Sell $500 → locked profit = $50
- At $125 (5R): Sell $150 → locked profit = $87.50
- Remaining: $350 position still running with trailing stop

---

## Risk Management

### Portfolio-Level Controls

1. **Maximum Positions**: 10 concurrent positions
2. **Maximum Exposure**: 90% of equity
3. **Maximum Single Position**: 15% of equity
4. **Risk Per Trade**: 2% of equity
5. **Consecutive Loss Limit**: Pause after 3 losses
6. **Emergency Stop**: Halt trading if drawdown > 15%

### Position-Level Controls

1. **Stop Loss**: -10% (regime-aware)
2. **Position Sizing**: Risk-based with exposure caps
3. **Partial Exits**: De-risk winners progressively
4. **Trailing Stops**: Protect profits dynamically
5. **Time Limits**: Force exits after max hold time

### Capital Preservation

The bot prioritizes **not losing money** over making money:

- Tight stop losses (-10% max)
- Fast momentum exits (5-20 minute reviews)
- Trailing stops activate early (+5%)
- Time exits prevent bag-holding
- Circuit breakers pause trading after losses

**Expected Outcome**: High win rate (55-65%) with small average wins and smaller losses.

---

## Execution Flow

### Trading Cycle (Every 15 Seconds)

```
1. START CYCLE
   ↓
2. WATCHER: Scan 36 pairs → 36 candidates
   ↓
3. ANALYZER: Analyze candidates → 12 setups
   ↓
4. CONTEXT: Enrich setups → 12 enriched setups (optional)
   ↓
5. BAYESIAN: Filter by confidence → 4-6 approved setups
   ↓
6. RISK MANAGER: Check each approved setup
   ├─ Already held? → Skip
   ├─ Max positions reached? → Skip
   ├─ Exposure too high? → Skip
   └─ OK → Calculate position size
   ↓
7. EXECUTION CORE: Place market buy order
   ├─ Success → Open position
   └─ Failure → Retry (max 5 attempts)
   ↓
8. POSITION MANAGER: Tick all open positions
   ├─ Check stop loss
   ├─ Check trailing stop
   ├─ Check momentum exits
   ├─ Check time exit
   ├─ Check tier exits
   └─ Execute exits if triggered
   ↓
9. BIGBROTHER: Update regime and parameters
   ↓
10. QUANT MUTATOR: Adjust thresholds
   ↓
11. UPDATE EQUITY: Fetch exchange balances
   ↓
12. BROADCAST: Send updates to dashboard via WebSocket
   ↓
13. SLEEP: Wait for next cycle (15s interval)
   ↓
14. REPEAT
```

### Entry Flow (Detailed)

```
APPROVED SETUP
   ↓
Risk Manager: can_open_position()
   ├─ Check: open_count < MAX_POSITIONS
   ├─ Check: exposure + new_position < MAX_EXPOSURE
   ├─ Check: symbol not in open_symbols
   └─ OK → compute_position_size()
   ↓
Position Size Calculation
   ├─ risk_amount = equity × 2%
   ├─ position_size = risk_amount / stop_loss_distance
   └─ position_size = min(position_size, equity × 15%)
   ↓
Execution Core: enter_position()
   ├─ Mode: paper → Simulate fill
   ├─ Mode: demo/live → Exchange API
   │   ├─ Attempt 1: create_market_buy()
   │   ├─ Fetch order status
   │   ├─ Parse fill data
   │   └─ If failed: Retry (max 5 attempts)
   └─ Return fill data
   ↓
Position Manager: open_position()
   ├─ Create Position object
   ├─ Set entry_price, amount, stop_loss, take_profits
   ├─ Add to _positions dict
   └─ Save to MongoDB
   ↓
POSITION OPENED
```

### Exit Flow (Detailed)

```
POSITION TICK (every cycle)
   ↓
Fetch current price
   ↓
Update highest_price if new high
   ↓
Calculate PnL%, R-multiple
   ↓
Update dynamic stop loss (if needed)
   ↓
Update trailing stop (if PnL ≥ +5%)
   ↓
CHECK EXIT CONDITIONS (priority order):
   ↓
1. Stop Loss?
   ├─ price ≤ stop_loss OR pnl_pct ≤ -10%
   └─ YES → Execute full exit (reason: stop_loss)
   ↓
2. Trailing Stop?
   ├─ trailing_stop exists AND price ≤ trailing_stop
   └─ YES → Execute full exit (reason: trailing_stop)
   ↓
3. Momentum Exit? (bot trades only)
   ├─ Check staged momentum conditions
   └─ YES → Execute full exit (reason: momentum_died_Xm)
   ↓
4. Time Exit?
   ├─ hold_time ≥ time_exit_hours
   └─ YES → Execute full exit (reason: time_exit)
   ↓
5. Tier 1 Exit?
   ├─ r_multiple ≥ 2.0 AND tier1_done == false
   └─ YES → Execute partial exit (50%, reason: tier1)
   ↓
6. Tier 2 Exit?
   ├─ r_multiple ≥ 5.0 AND tier2_done == false
   └─ YES → Execute partial exit (30%, reason: tier2)
   ↓
NO EXIT TRIGGERED → Continue holding
```

### Limit-First Exit Execution (New in v2.0)

```
EXIT TRIGGERED
   ↓
Execution Core: exit_position()
   ↓
Fetch actual exchange balance (avoid BALANCE_NOT_ENOUGH)
   ↓
Cap sell amount to available balance × 99.5%
   ↓
ATTEMPT 1: Initial limit order
   ├─ Fetch order book
   ├─ Calculate limit price = best_ask × 1.0008 (+8 bps)
   ├─ Place limit sell order
   ├─ Poll order status (every 3s, max 10 polls)
   ├─ Filled? → Return fill data
   └─ Not filled → Cancel order, proceed to ATTEMPT 2
   ↓
ATTEMPT 2: Repriced limit order
   ├─ Calculate limit price = previous - 6 bps
   ├─ Place limit sell order
   ├─ Poll order status
   ├─ Filled? → Return fill data
   └─ Not filled → Cancel order, proceed to ATTEMPT 3
   ↓
ATTEMPT 3-4: Continue repricing
   ↓
ATTEMPT 5: Final aggressive limit
   ├─ Calculate limit price = best_bid × 0.9998 (-2 bps, crosses spread)
   ├─ Place limit sell order
   ├─ Poll order status
   └─ Filled? → Return fill data
   ↓
If partial fill:
   ├─ Update position.amount -= filled_amount
   ├─ Book partial PnL
   └─ Keep position open for remainder
   ↓
If full fill:
   ├─ Mark position as closed
   ├─ Book final PnL
   ├─ Add to closed_history
   └─ Remove from _positions
   ↓
EXIT COMPLETE
```

**Why This Approach?**
- Avoids market sell slippage
- Captures better prices in volatile markets
- Professional execution quality
- Still aggressive enough to ensure fills (final attempt crosses spread)

---

## Data Flow

### Data Sources

1. **Exchange (Gate.io)**
   - OHLCV data (5m, 15m, 1h, 4h timeframes)
   - Order book data
   - Account balances
   - Order status

2. **Redis Cache**
   - OHLCV data (5-minute TTL)
   - Reduces API calls by ~95%
   - Shared across all agents

3. **MongoDB**
   - Trade history
   - Position snapshots
   - Performance metrics
   - Configuration backups

### Data Caching Strategy

```
Agent requests OHLCV data
   ↓
Check Redis cache
   ├─ Cache hit? → Return cached data (fast)
   └─ Cache miss? → Fetch from exchange API
       ↓
       Store in Redis (TTL: 5 minutes)
       ↓
       Return data
```

**Cache Performance**:
- Hit rate: ~95%
- Latency: <5ms (cached) vs ~200ms (API)
- API calls saved: ~1,000 per hour

### State Management

**In-Memory State** (FastAPI backend):
- Open positions (`_positions` dict)
- Closed history (last 200 trades)
- Current equity
- Cycle count
- Agent status

**Persistent State** (MongoDB):
- All trades (permanent record)
- Position snapshots (hourly)
- Equity history (per cycle)
- Configuration changes

**WebSocket Broadcasts**:
- Position updates
- Trade executions
- Equity changes
- Agent status
- Cycle traces

---

## Configuration

### Environment Variables

All configuration is managed via `.env` file:

```bash
# Exchange
EXCHANGE=gateio
EXCHANGE_MODE=demo  # paper, demo, live
GATE_API_KEY=your_key
GATE_API_SECRET=your_secret

# Trading Parameters
MAX_POSITIONS=10
MAX_TOTAL_EXPOSURE_PCT=90.0
MAX_SINGLE_EXPOSURE_PCT=15.0
RISK_PER_TRADE_PCT=2.0

# Exit Parameters
STOP_LOSS_PCT=-10.0
TRAILING_STOP_ACTIVATE_PCT=5.0
TRAILING_STOP_DISTANCE_PCT=3.5
TIME_EXIT_HOURS=1.5
MOMENTUM_RECHECK_INTERVAL_MINUTES=5

# Execution
MAX_SELL_RETRIES=5
EXIT_LIMIT_POLL_SECONDS=3
EXIT_LIMIT_INITIAL_MARKUP_BPS=8
EXIT_LIMIT_REPRICE_STEP_BPS=6
EXIT_LIMIT_FINAL_CROSS_BPS=2

# Bayesian
BAYESIAN_THRESHOLD=0.22
BAYESIAN_MODE=normal

# Agents
WATCHER_MIN_SCORE=20.0
ANALYZER_MIN_SCORE=15.0
CONTEXT_ENABLED=false

# Database
MONGO_URI=mongodb://localhost:27017
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Runtime Configuration

Some parameters are adjusted dynamically by BigBrother and Quant Mutator:

- `min_score`: 15.0 → 25.0 (based on setup quality)
- `bayesian_threshold`: 0.22 → 0.28 (based on win rate)
- Regime parameters: Adjusted by market conditions

---

## Deployment

### System Requirements

- **OS**: macOS, Linux (Ubuntu 20.04+)
- **Python**: 3.11+
- **Node.js**: 18+
- **MongoDB**: 5.0+
- **Redis**: 6.0+
- **RAM**: 2GB minimum, 4GB recommended
- **CPU**: 2 cores minimum
- **Disk**: 10GB minimum

### Services

1. **Backend** (FastAPI)
   - Port: 8000
   - Process: `uvicorn backend.server:app`
   - Logs: `/logs/backend.log`

2. **Frontend** (Next.js)
   - Port: 3001
   - Process: `npm run dev` (dev) or `npm start` (prod)
   - Logs: `/logs/frontend.log`

3. **TinyOffice** (Chat Interface)
   - Port: 3000
   - Process: `npm run dev`
   - Logs: `/logs/tinyoffice.log`

4. **MongoDB**
   - Port: 27017
   - Data: `/data/db`

5. **Redis**
   - Port: 6379
   - Data: In-memory

### Startup Scripts

**Start All Services**:
```bash
./start_all.sh
```

**Stop All Services**:
```bash
./stop_all.sh
```

**Stop and Sell All Positions**:
```bash
./stopandsell_all.sh
```

### Process Management

Services run in `screen` sessions for persistence:
- `moonshot-frontend`: Frontend dashboard
- `moonshot-tinyoffice`: Chat interface
- Backend runs as background process with PID file

### Health Checks

Backend health endpoint:
```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "exchange": "gateio",
  "exchange_mode": "demo",
  "running": true,
  "paused": false,
  "uptime": 3600,
  "cycle": 240
}
```

---

## Monitoring & Observability

### Dashboard (http://localhost:3001)

**Components**:
1. **SwarmControl**: Start/stop/pause controls, equity display
2. **PositionsGrid**: Live open positions with PnL
3. **TradeLog**: Recent trade history with color-coded sides
4. **PnLChart**: Equity curve over time
5. **NeuralFeed**: Agent activity and cycle traces
6. **AgentStatus**: Health status of all agents

### Metrics (Prometheus)

**Exposed Metrics**:
- `trades_total{side, exchange}`: Total trades executed
- `errors_total{component, error_type}`: Error counts
- `active_positions`: Current open position count
- `cycle_duration_seconds`: Cycle execution time

**Endpoint**: `http://localhost:8000/metrics`

### Logging

**Log Levels**:
- `INFO`: Normal operations (cycles, trades, exits)
- `WARNING`: Recoverable issues (retries, skipped entries)
- `ERROR`: Failures (order errors, API failures)
- `DEBUG`: Detailed diagnostics (disabled in production)

**Log Files**:
- `/logs/backend.log`: Main trading bot logs
- `/logs/frontend.log`: Dashboard logs
- `/logs/tinyoffice.log`: Chat interface logs

**Key Log Patterns**:

Entry:
```
[Swarm] ENTERED BTC/USDT: entry=74120.4 size=$1500 posterior=0.974
```

Exit:
```
[PM] CLOSED BTC/USDT (momentum_died_15m): pnl=$-15.20 (-1.0%) hold=0.3h
```

Cycle trace:
```
[Cycle 42] watcher:36 → analyzer:12 → bayesian:4 → entries:2
```

### API Endpoints

**Status**:
- `GET /health`: System health
- `GET /api/agents`: Agent status
- `GET /api/swarm/status`: Trading status

**Data**:
- `GET /api/portfolio`: Portfolio summary
- `GET /api/positions`: Open positions
- `GET /api/trades`: Trade history
- `GET /api/equity/history`: Equity curve

**Control**:
- `POST /api/swarm/start`: Start trading
- `POST /api/swarm/stop`: Stop trading
- `POST /api/swarm/pause`: Pause trading
- `POST /api/swarm/close-all-positions`: Emergency liquidation

**WebSocket**:
- `WS /ws`: Real-time updates

---

## Autonomy Level

### Fully Autonomous Operations

The bot handles **100% autonomously**:

1. ✅ Market scanning and opportunity identification
2. ✅ Technical analysis and setup generation
3. ✅ Risk assessment and position sizing
4. ✅ Order placement and execution
5. ✅ Position monitoring and exit decisions
6. ✅ Trailing stop management
7. ✅ Partial exit execution (tier exits)
8. ✅ Regime detection and parameter adaptation
9. ✅ Performance tracking and optimization
10. ✅ Error recovery and retry logic

### Manual Interventions (Optional)

The bot **does not require** but **allows**:

1. Manual position closure via dashboard
2. Emergency stop via API or dashboard
3. Parameter adjustments via `.env` file (requires restart)
4. Mode switching (paper/demo/live)

### Safety Mechanisms

**Automatic Protections**:
- Stop losses on all positions
- Trailing stops on profitable positions
- Time exits to prevent bag-holding
- Exposure limits to prevent over-concentration
- Circuit breakers after consecutive losses
- Emergency stop on excessive drawdown

**Human Oversight**:
- Real-time dashboard monitoring
- Trade log review
- Performance metrics tracking
- Alert notifications (optional)

---

## Performance Expectations

### Target Metrics

- **Win Rate**: 55-65%
- **Average R-Multiple**: 1.5-2.5
- **Max Drawdown**: <15%
- **Sharpe Ratio**: >1.0
- **Average Hold Time**: 30 minutes - 2 hours
- **Trades Per Day**: 10-20 (depending on market conditions)

### Risk Profile

- **Conservative**: Low leverage, tight stops, high selectivity
- **Capital Preservation**: Prioritizes not losing over winning big
- **Momentum-Focused**: Designed for trending markets, struggles in chop

### Known Limitations

1. **Sideways Markets**: Lower win rate in range-bound conditions
2. **Low Liquidity**: May struggle with illiquid pairs
3. **Flash Crashes**: Stop losses can get slipped in extreme volatility
4. **API Limits**: Rate-limited by exchange (mitigated by caching)
5. **Slippage**: Market orders can experience slippage (mitigated by limit-first exits)

---

## Recent Enhancements (v2.0)

### March 2026 Updates

1. **Adaptive Momentum Exits**
   - Replaced single 15-minute cutoff with staged 5-minute reviews
   - Positions re-evaluated at 5m, 10m, 15m, 20m intervals
   - Winners allowed to run, losers cut faster

2. **Limit-First Exit Execution**
   - Replaced market sells with intelligent limit order repricing
   - Initial limit at +8 bps, reprices down to -2 bps
   - Reduces slippage and improves execution quality

3. **Exchange Holdings Protection**
   - Fixed bug where exchange holdings had no exit protection
   - Now receive dynamic stop loss and time exit
   - Prevents indefinite bleeding of synced positions

4. **Partial Fill Handling**
   - Correctly handles partial limit order fills
   - Updates position amount without falsely closing
   - Books partial PnL accurately

5. **Regime-Aware Time Exits**
   - Time exit now uses regime_params dynamically
   - Adjusts from 1.5h (bear) to 5h (bull)

---

## Conclusion

Moonshot-CEX is a **production-grade, fully autonomous trading system** designed for cryptocurrency spot trading. It combines:

- **Multi-agent architecture** for specialized task handling
- **Bayesian inference** for probabilistic decision-making
- **Adaptive strategy** that adjusts to market conditions
- **Professional execution** with limit-first order placement
- **Comprehensive risk management** at portfolio and position levels
- **Real-time monitoring** via WebSocket dashboard

The system is designed to operate **24/7 without human intervention**, making intelligent trading decisions based on technical analysis, risk management, and performance feedback.

**Key Strengths**:
- Fully autonomous operation
- Sophisticated exit strategy with staged momentum reviews
- Professional limit-first execution
- Adaptive parameter management
- Comprehensive risk controls

**Best Use Cases**:
- Trending cryptocurrency markets
- Short-term momentum trading
- Automated portfolio management
- Hands-off trading for busy traders

**Not Suitable For**:
- Buy-and-hold strategies
- Range-bound markets (lower performance)
- Ultra-high-frequency trading
- Leveraged/futures trading (spot only)

---

**Version History**:
- v1.0 (Jan 2026): Initial release with basic multi-agent system
- v1.5 (Feb 2026): Added BigBrother regime detection and Quant Mutator
- v2.0 (Mar 2026): Adaptive exits, limit-first execution, exchange holdings protection

**Maintainer**: Vishnu Vardhan Medara  
**License**: Proprietary  
**Last Updated**: March 18, 2026
