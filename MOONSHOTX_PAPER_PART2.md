## 5. Multi-Agent Intelligence Layer

### 5.1 Agent Roster

| Agent | LLM Tier | Role | Tools |
|---|---|---|---|
| Technical Analyst | Quick-think | Price action, indicators, patterns | `get_stock_data`, `get_indicators` |
| Sentiment Analyst | Quick-think | Social media & retail sentiment | `get_news` (social) |
| News Analyst | Quick-think | Breaking news, macro events | `get_news`, `get_global_news`, `get_insider_transactions` |
| Fundamentals Analyst | Quick-think | Financials, earnings, valuations | `get_fundamentals`, `get_balance_sheet`, `get_cashflow` |
| Bull Researcher | Quick-think | Build bullish case from reports | Memory-augmented |
| Bear Researcher | Quick-think | Build bearish case from reports | Memory-augmented |
| Research Manager | **Deep-think** | Judge debate, synthesize verdict | Memory-augmented |
| Trader | Quick-think | Create entry plan (ticker, size, SL, TP) | Memory-augmented |
| Aggressive Analyst | Quick-think | Argue for larger position / tighter SL | None |
| Neutral Analyst | Quick-think | Balance risk/reward objectively | None |
| Conservative Analyst | Quick-think | Argue for smaller position / rejection | None |
| Portfolio Manager | **Deep-think** | Final APPROVE/REJECT | Memory-augmented |

### 5.2 LangGraph Flow

```
START
  → [Technical Analyst] → tools_market → Msg Clear
  → [Sentiment Analyst] → tools_social → Msg Clear
  → [News Analyst] → tools_news → Msg Clear
  → [Fundamentals Analyst] → tools_fundamentals → Msg Clear
  → [Bull Researcher] ↔ [Bear Researcher]  (N debate rounds)
  → [Research Manager]  (judge verdict)
  → [Trader]  (execution plan)
  → [Aggressive] ↔ [Conservative] ↔ [Neutral]  (M risk rounds)
  → [Portfolio Manager]  (APPROVE / REJECT)
END
```

### 5.3 Debate Mechanism

**Investment Debate (Bull vs Bear):**
- Bull receives all analyst reports, builds strongest case for buying
- Bear builds strongest case against
- Alternate for `max_debate_rounds` (default: 2), each responding to the other
- Research Manager reads full debate history, issues verdict with reasoning

**Risk Debate (3-way):**
- **Aggressive**: "Strong setup, increase size, tighten stop for better R:R"
- **Conservative**: "Too risky, reduce size, wider stop, or reject entirely"
- **Neutral**: "Objective risk/reward — here's my balanced recommendation"
- Portfolio Manager makes final call after reading all perspectives

### 5.4 Memory & Reflection

Each memory-augmented agent has `FinancialSituationMemory`:

```python
# After trade closes — reflection
for agent in [bull, bear, trader, research_manager, portfolio_manager]:
    situation = extract_market_situation(trade_state)
    reflection = agent.reflect(trade_outcome, situation)  # LLM call
    agent.memory.add_situations([(situation, reflection)])

# Before new decision — retrieval
similar = agent.memory.retrieve(current_situation, top_k=3)
# Injected into agent system prompt for context
```

Reflection prompt asks each agent:
1. Was this decision correct? Why?
2. What factors were missed or overweighted?
3. What would you do differently?
4. Extract a 1-sentence lesson for future reference.

---

## 6. Strategy Engine

### 6.1 Universe Scanner (NEW)

```python
UNIVERSE_CRITERIA = {
    "min_market_cap": 10_000_000_000,   # $10B+ large cap
    "min_avg_volume": 5_000_000,         # 5M+ shares/day
    "min_price": 20.0,                   # No penny stocks
    "max_price": 1000.0,                 # No illiquid giants
    "exchanges": ["NYSE", "NASDAQ"],
}

# Pre-market ranking (9:00 AM ET daily)
def rank_universe():
    stocks = filter_by_criteria(UNIVERSE_CRITERIA)
    for s in stocks:
        s.composite = (0.4 * momentum_20d(s)
                      + 0.3 * volume_surge(s)
                      + 0.3 * gap_pct(s))
    return sorted(stocks, key=lambda s: s.composite, reverse=True)[:50]
```

### 6.2 Wave Rider Entry (from DayTraderAI)

```python
WAVE_ENTRY_CONDITIONS = {
    "trend": "5m/15m EMA9 > EMA21, 1h bullish",
    "momentum": "RSI 40-75, MACD histogram > 0",
    "volume": "> 1.2x average",
    "timing": "Pullback to EMA9/21 zone, bounce confirmation",
    "agents": "BUY decision, Portfolio Manager APPROVED",
    "bayesian": "Posterior ≥ 0.45",
}
```

### 6.3 Momentum Fast-Track (from Moonshot-CEX)

If 1h return > 2% AND volume > 2x average → skip EMA/MACD gates, proceed directly to agent evaluation. Still requires agent consensus + Bayesian threshold.

### 6.4 Multi-Timeframe Weights

| Timeframe | Weight | Purpose |
|---|---|---|
| 5-minute | 15% | Entry timing |
| 15-minute | 30% | Trend confirmation |
| 1-hour | 35% | Primary trend |
| 4-hour | 15% | Higher TF context |
| Daily | 5% | Major S/R levels |

---

## 7. Risk Management Framework

### 7.1 Five-Tier Risk Hierarchy

```
TIER 1: PORTFOLIO
├── Max drawdown: 10% → FULL HALT
├── Recovery: resume at 7% drawdown
└── Account < initial × 0.85 → SHUTDOWN

TIER 2: DAILY
├── Max daily loss: 3% → stop for the day
├── Max daily trades: 15
└── 3 consecutive losses → 30 min pause

TIER 3: POSITION
├── Max positions: 5 (bull), 3 (bear/choppy)
├── Max single position: 4% of portfolio
├── Max sector exposure: 20%
└── Max correlated positions: 2

TIER 4: ENTRY
├── Bayesian posterior ≥ 0.45
├── Agent consensus: Portfolio Manager APPROVED
├── Symbol cooldown: 4 hours
└── No entry after 15:30 ET

TIER 5: EXECUTION
├── Bracket orders mandatory
├── 5-second stop verification loop
├── Market sells for SL/trailing exits
├── Fill detection 30s timeout
└── Max slippage: 0.3%
```

### 7.2 Position Sizing (ATR-Based, Regime-Adjusted)

```python
def calculate_position_size(ticker, entry, stop, regime):
    base_risk = 0.015  # 1.5% per trade
    regime_mult = {"bull": 1.2, "neutral": 1.0, "fear": 0.8, "extreme_fear": 0.5}
    risk_pct = base_risk * regime_mult[regime]
    dollar_risk = portfolio_value * risk_pct
    stop_distance = abs(entry - stop) / entry
    position_value = min(dollar_risk / stop_distance, portfolio_value * 0.04)
    return int(position_value / entry)
```

### 7.3 Regime Detection (Enhanced — 4 inputs)

| Input | Source | Regimes |
|---|---|---|
| Fear & Greed Index | CNN scraper | Extreme Fear → Extreme Greed (0-100) |
| VIX | CBOE | Low (<15) → Crisis (>35) |
| Market Breadth | % S&P 500 > 200d MA | Strong Bear (<20%) → Strong Bull (>70%) |
| Momentum | 20-day S&P return | Strong Down (<-5%) → Strong Up (>5%) |

Regime-specific parameter scaling (from Moonshot-CEX BigBrother):

| Regime | SL Mult | Trail Mult | Time Mult | Max Positions |
|---|---|---|---|---|
| Bull | 1.4× | 1.3× | 1.5× | 5 |
| Neutral | 1.0× | 1.0× | 1.0× | 4 |
| Fear | 0.7× | 0.8× | 0.6× | 3 |
| Choppy | 0.65× | 0.7× | 0.5× | 2 |

---

## 8. Execution Engine (from DayTraderAI)

### 8.1 Order Flow

```python
async def enter_position(ticker, shares, stop_price, tp_price):
    # 1. Pre-flight: market open, risk limits OK, position count OK
    # 2. Bracket order via Alpaca (SL + TP from birth)
    order = api.submit_order(
        symbol=ticker, qty=shares, side='buy', type='market',
        time_in_force='day', order_class='bracket',
        stop_loss={'stop_price': stop_price},
        take_profit={'limit_price': tp_price})
    # 3. Fill detection (30s timeout)
    filled = await fill_detection.wait_for_fill(order.id, timeout=30)
    if not filled: api.cancel_order(order.id); return None
    # 4. Register in position manager
    position_manager.register(Position(...))
```

### 8.2 Execution Rules (Battle-Tested)

| Rule | Rationale |
|---|---|
| Market sells for SL/trailing | IOC limits fail in fast markets (-$747 XRP lesson) |
| Bracket orders mandatory | Every position has SL + TP from birth |
| 5-second stop verification | Catches orphaned/failed stop orders |
| Fill detection + timeout | Prevents phantom positions |
| Max slippage 0.3% | Rejects fills beyond acceptable range |
| No entry after 15:30 ET | Low liquidity, high spread |
| EOD exit at 15:57 ET | Prevents overnight gap risk |
| 4-hour symbol cooldown | Prevents re-entry churn |

---

## 9. Position Management

### 9.1 Exit Hierarchy (Evaluated Every 5 Seconds)

| Priority | Exit | Condition | Action |
|---|---|---|---|
| 1 | **Stop Loss** | pnl ≤ -SL% (ATR-based, ~1.5-2%) | MARKET SELL 100% |
| 2 | **Trailing Stop** | Activated at +1%, distance 1% | MARKET SELL 100% |
| 3 | **Partial Profit 2R** | R-multiple ≥ 2.0 | SELL 50%, move SL to breakeven |
| 4 | **Partial Profit 3R** | R-multiple ≥ 3.0 | SELL 25% remaining, trail rest |
| 5 | **Breakeven** | R-multiple ≥ 1.0 | Move SL to entry price |
| 6 | **Time Exit** | Hold ≥ 3h AND pnl ≤ 0 | MARKET SELL 100% |
| 7 | **Time Exit Max** | Hold ≥ 6h (any pnl) | MARKET SELL 100% |
| 8 | **Momentum Faded** | Peak ≥ 3%, gave back 60%+, pnl < 0.5% | MARKET SELL 100% |
| 9 | **EOD Exit** | Time ≥ 15:57 ET (day mode) | MARKET SELL 100% |

### 9.2 R-Multiple Tracking (from DayTraderAI)

```python
class RMultipleTracker:
    def __init__(self, entry_price, stop_price):
        self.entry = entry_price
        self.risk = abs(entry_price - stop_price)  # 1R = this distance
        self.peak_r = 0.0

    def current_r(self, price):
        return (price - self.entry) / self.risk

    def update(self, price):
        r = self.current_r(price)
        self.peak_r = max(self.peak_r, r)
        return r
```

### 9.3 Trailing Stop Modes

| Mode | Activation | Distance | Use Case |
|---|---|---|---|
| Standard | +1.0% | 1.0% | Default |
| ATR-Based | 1.0 × ATR | 1.5 × ATR | Volatile stocks |
| Regime-Scaled | Standard × mult | Standard × mult | Auto-adapts |
| Chandelier | Highest high - 3×ATR | Dynamic | Swing trades |

---

## 10. Learning & Reflection System

### 10.1 Post-Trade Reflection (from TradingAgents)

After every trade closes, each agent reviews the outcome:
- Was the decision correct?
- What factors were missed or overweighted?
- What would you do differently?
- Extract a 1-sentence lesson

Results stored in `FinancialSituationMemory` for retrieval in similar future situations.

### 10.2 QuantMutator (from Moonshot-CEX, with fixes)

```python
class QuantMutator:
    FLOOR = 0.40      # NEVER below (0.12 destroyed us)
    CEILING = 0.55    # Don't block all entries
    DEFAULT = 0.45

    def mutate(self, win_rate, day_pnl_pct, threshold):
        if win_rate >= 0.65:  # Hot streak
            return max(self.FLOOR, threshold - 0.02), "hot_streak"
        elif win_rate <= 0.35:  # Cold streak
            return min(self.CEILING, threshold + 0.02), "cold_streak"
        elif day_pnl_pct < -0.03:  # Emergency
            return min(self.CEILING, threshold + 0.03), "emergency"
        return threshold, "no_change"
```

### 10.3 Weekly Parameter Optimization (from DayTraderAI)

Bayesian optimization of key parameters every Sunday against Sharpe ratio from last 20 trading days:
- `stop_loss_atr_mult`: range (1.0, 3.0)
- `trailing_activate_pct`: range (0.5, 2.0)
- `trailing_distance_pct`: range (0.5, 2.0)
- `rsi_entry_low/high`: ranges (30-50, 65-80)
- `time_exit_hours`: range (2, 6)

---

## 11. Data Infrastructure

### 11.1 Sources

| Source | Data | Frequency | Cost |
|---|---|---|---|
| Alpaca WebSocket | Real-time bars (1m/5m/15m) | Real-time | Free |
| Alpaca REST | Historical bars, account | On-demand | Free |
| yFinance | Fundamentals, earnings, news | Pre-market | Free |
| CNN Fear & Greed | F&G Index (0-100) | 15 min | Free |
| CBOE VIX | Volatility Index | Real-time | Free |
| Twelve Data | Daily bars cache | Daily | Free tier |
| Polygon.io | Tick-level historical | Backtest | $29/mo |

### 11.2 Feature Engine (50+ Indicators)

**Trend:** EMA 9/21/50/200, SMA 20/50/200
**Momentum:** RSI 14/7, MACD, Stochastic K/D, Williams %R, CCI
**Volatility:** ATR 14/7, Bollinger Bands, Keltner Channels
**Volume:** VWAP, Volume SMA 20, OBV, MFI, Volume Ratio
**Price Action:** Support/Resistance, Pivot Points, Candlestick Patterns
**Custom:** 1h Momentum, Gap %, Relative Strength vs SPY

---

## 12. Backtesting & Validation

### 12.1 Validation Protocol

| Phase | Duration | Capital | Risk |
|---|---|---|---|
| 1. Backtest | 2yr historical | Simulated $50K | None |
| 2. Paper Trade | 30 days | Alpaca paper | None |
| 3. Micro Live | 30 days | $5K real | Very low |
| 4. Small Live | 60 days | $25K real | Low |
| 5. Full Live | Ongoing | $50K+ real | Normal |

### 12.2 Go/No-Go Criteria

| Metric | Phase 2→3 | Phase 3→4 | Phase 4→5 |
|---|---|---|---|
| Win Rate | ≥ 55% | ≥ 55% | ≥ 55% |
| Profit Factor | ≥ 1.5 | ≥ 1.8 | ≥ 2.0 |
| Max Drawdown | < 15% | < 12% | < 10% |
| Sharpe Ratio | ≥ 1.5 | ≥ 1.8 | ≥ 2.0 |
| Total Trades | ≥ 50 | ≥ 100 | ≥ 200 |

---

## 13. Implementation Roadmap

### Phase 0: Foundation (Weeks 1-2)
- Set up monorepo structure
- Port Alpaca integration from DayTraderAI
- Port Feature Engine (50+ indicators)
- Port yFinance data layer from TradingAgents
- Set up Supabase schema
- Unified config system

### Phase 1: Intelligence Layer (Weeks 3-5)
- Port LangGraph setup from TradingAgents
- Adapt 4 analyst agents for real-time stock analysis
- Implement Bull/Bear debate with memory
- Implement 3-way Risk debate
- Port FinancialSituationMemory
- Integrate Bayesian pre-filter from Moonshot-CEX
- Build real-time trading loop

### Phase 2: Execution & Position Management (Weeks 6-8)
- Port Smart Order Executor from DayTraderAI
- Port bracket order system
- Build merged Position Manager (DayTraderAI + Moonshot-CEX exits)
- Implement R-multiple tracking + trailing stop modes
- 5-second stop verification loop
- Fill detection engine

### Phase 3: Risk Management (Weeks 9-10)
- 5-tier risk hierarchy
- Enhanced regime detection (VIX + F&G + Breadth + Momentum)
- QuantMutator with hard floors
- Circuit breakers + position sizing

### Phase 4: Learning & Optimization (Weeks 11-12)
- Reflection system from TradingAgents
- Memory retrieval for agent decisions
- Parameter optimizer from DayTraderAI
- Weekly auto-optimization pipeline

### Phase 5: Frontend & Monitoring (Weeks 13-14)
- React dashboard (from DayTraderAI)
- Agent decision audit trail
- Real-time position/PnL display
- Performance charts + alerts

### Phase 6: Validation (Weeks 15-18)
- Backtesting framework
- 2-year backtest
- Paper trade 30 days
- Micro live ($5K) 30 days
- Iterate

**Total: ~18 weeks (4.5 months) to micro-live.**

---

## 14. Proposed File Structure

```
moonshotx/
├── backend/
│   ├── server.py                     # FastAPI main
│   ├── config.py                     # Unified config
│   ├── agents/                       # From TradingAgents
│   │   ├── analysts/                 # technical, sentiment, news, fundamentals
│   │   ├── researchers/              # bull, bear
│   │   ├── managers/                 # research_manager, portfolio_manager
│   │   ├── risk_mgmt/               # aggressive, neutral, conservative
│   │   ├── trader/
│   │   └── utils/                    # memory, states, utils
│   ├── graph/                        # LangGraph orchestration
│   │   ├── trading_graph.py, setup.py, propagation.py
│   │   ├── reflection.py, signal_processing.py
│   │   └── conditional_logic.py
│   ├── data/                         # From DayTraderAI
│   │   ├── market_data.py            # Alpaca WS
│   │   ├── features.py              # 50+ indicators
│   │   ├── daily_cache.py
│   │   └── dataflows/               # yFinance (from TradingAgents)
│   ├── trading/                      # Merged DayTraderAI + Moonshot-CEX
│   │   ├── position_manager.py       # Merged exit system
│   │   ├── risk_manager.py           # 5-tier + regime
│   │   ├── regime_manager.py         # VIX + F&G + Breadth
│   │   ├── trailing_stops.py, stop_loss_protection.py
│   │   ├── profit_taker.py, breakeven_manager.py
│   │   ├── wave_entry.py, symbol_cooldown.py
│   │   ├── universe_scanner.py       # NEW
│   │   ├── bayesian_engine.py        # From Moonshot-CEX
│   │   └── quant_mutator.py          # From Moonshot-CEX
│   ├── orders/                       # From DayTraderAI
│   │   ├── smart_order_executor.py
│   │   ├── bracket_orders.py
│   │   └── fill_detection_engine.py
│   ├── adaptive/                     # From DayTraderAI
│   │   └── parameter_optimizer.py
│   └── backtest/                     # NEW
│       ├── backtester.py
│       └── simulated_broker.py
├── frontend/                         # From DayTraderAI (React)
│   └── src/components/
│       ├── Dashboard, PositionTable, AgentAuditTrail
│       ├── EquityCurve, RegimeIndicator
│       └── ...
└── tests/
```

---

## 15. Configuration Reference

```python
MOONSHOTX_CONFIG = {
    # LLM
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.2",
    "quick_think_llm": "gpt-5-mini",
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,

    # Trading
    "risk_per_trade_pct": 0.015,
    "max_positions": 5,
    "max_single_position_pct": 0.04,
    "max_sector_exposure_pct": 0.20,
    "max_daily_loss_pct": 0.03,
    "max_drawdown_pct": 0.10,

    # Entry
    "bayesian_threshold": 0.45,
    "bayesian_floor": 0.40,
    "bayesian_ceiling": 0.55,
    "symbol_cooldown_hours": 4,
    "entry_cutoff_time": "15:30",

    # Exits
    "stop_loss_atr_mult": 1.5,
    "trailing_activate_pct": 0.01,
    "trailing_distance_pct": 0.01,
    "time_exit_hours": 3.0,
    "time_exit_max_hours": 6.0,
    "eod_exit_time": "15:57",
    "partial_profit_2r_pct": 0.50,
    "partial_profit_3r_pct": 0.25,
    "breakeven_r_trigger": 1.0,

    # Data
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    },
}
```

---

## 16. Risk Disclosures

**Technical Risks:** LLM latency (10-30s, mitigated by Bayesian pre-filter), hallucination (mitigated by debate + mechanical exits), API rate limits (200 req/min, mitigated by caching).

**Market Risks:** Flash crashes (5s stop verification + market sells), gap risk (EOD exit), regime misclassification (4 independent inputs), correlation risk (max 2 correlated positions).

**Operational Risks:** Server downtime (VPS 99.9% SLA, auto-restart), broker API outage (server-side bracket orders persist), memory corruption (Supabase crash-resistant state).

> **DISCLAIMER:** This system is for educational and research purposes only. Trading US stocks involves substantial risk of loss. Past performance does not guarantee future results. Never risk more than you can afford to lose. Consult a qualified financial advisor before trading with real capital.

---

*End of MoonshotX Product & Technical Paper v1.0*
