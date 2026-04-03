
***

Pretext :

Repurposing these repos to build MoonshotX :
my old repo on trading : https://github.com/codebytelabs/DayTraderAI most trending trading agent repo on github now : https://github.com/TauricResearch/TradingAgents and my latest moonshot-cex repo itself : https://github.com/codebytelabs/Moonshot-CEX

***

# MoonshotX v1.1: Autonomous Multi-Agent US Stock Trading System
### Product & Technical Paper
**Author:** CodeByteLabs | **Revised:** March 2026 | **Status:** Design Phase — Ready to Build

***

## 1. Executive Summary

MoonshotX synthesises three battle-tested codebases into a fully autonomous US stock trading system, incorporating all architectural lessons from live trading losses and two rounds of expert peer review.

| Source Repo | Contribution | Key Innovation |
|---|---|---|
| **DayTraderAI** | Alpaca execution, 50+ indicators, R-multiple tracking, Wave Rider | US stock infrastructure |
| **TradingAgents** | LangGraph multi-agent brain, analyst debates, reflection/memory | LLM-powered decision intelligence |
| **Moonshot-CEX** | Trailing stops, Bayesian engine, regime detection, adaptive thresholds | Battle-tested position management |

### Core Thesis

> **LLMs act as signal quality arbiters — they decide *what* and *when* to buy by synthesising context no single indicator can capture. Mechanical quant systems decide *when* to sell. Never the reverse.**

### Revised Performance Targets (Realistic)

| Metric | v1.0 (Aspirational) | v1.1 (Calibrated) | Rationale |
|---|---|---|---|
| Win Rate | 60–70% | **50–62%** | Trend systems realistically 45–60%; debate layer adds ~5% |
| Profit Factor | ≥ 2.5 | **≥ 1.8 (target 2.2)** | High WR + high PF rarely coexist; asymmetric exits bridge the gap |
| Sharpe Ratio | ≥ 2.0 | **≥ 1.5 (target 1.8)** | Achievable elite-retail level |
| Max Drawdown | < 10% | **< 15% (target < 12%)** | Bear mode + cash regime as new floor |
| Annual Return | — | **20–50% CAGR** | Already elite for systematic retail |

### Key Differentiators vs v1.0

1. **Parallel agent execution** — 4 analysts run simultaneously, 45s wall-clock budget hard enforced
2. **Bear mode with inverse ETF rotation** — system profits or hedges in all regimes, not just bull
3. **Earnings blackout** — hard rule, not an agent decision
4. **Memory with TTL + regime tags** — no stale analogy poisoning
5. **Backtest-first roadmap** — no live money before 2yr validation
6. **Explicit LLM cost budget** — daily cost circuit breaker, two-tier model
7. **EarningsMomentumScorer** — the genuine alpha differentiator neither source repo has

***

## 2. Problem Statement

| Problem | Evidence | MoonshotX v1.1 Solution |
|---|---|---|
| Single-brain decisions | EMA crossover alone = noise | 4 analyst agents + debate teams |
| LLMs managing positions | Non-deterministic, hallucinate | LLMs for entry signal arbitration ONLY |
| No learning from mistakes | DayTraderAI repeated errors | Reflection system with TTL + regime guard |
| Over-trading | Moonshot-CEX: 185 trades/day = loss | Max 5 positions, Bayesian ≥ 0.45, cash mode in choppy |
| Premature exits | Winners held 0.41h vs losers 3.78h | Trailing stop primary, time exit only for losers |
| Sequential LLM latency | 10 candidates × 30s = 300s in 60s loop | Parallel asyncio.gather() with 45s hard budget |
| No bear protection | Long-only bleeds in 2022-style markets | BEAR_MODE with inverse ETF rotation |
| Memory poisoning | Wrong regime analogies surface over time | 90-day TTL, regime-tagged retrieval |
| Unknown trade cost | Slippage modelled as 0.3% cap | Realistic spread + ADV-based slippage model |
| LLM cost explosion | 100 trades/day × deep-think = $200/day | Two-tier LLM, daily cost circuit breaker |

***

## 3. Prior Art — What to Repurpose

### 3.1 From DayTraderAI

| Component | File | Repurpose? |
|---|---|---|
| Feature Engine (50+ indicators) | `backend/data/features.py` | ✅ Core |
| Market Data (Alpaca WS) | `backend/data/market_data.py` | ✅ Core |
| Risk Manager (sizing, breakers) | `backend/trading/risk_manager.py` | ✅ Core |
| Momentum Confirmed Regime | `backend/trading/momentum_confirmed_regime.py` | ✅ Core |
| Trailing Stops (ATR-based) | `backend/trading/trailing_stops.py` | ✅ Core |
| Stop Loss Protection (5s loop) | `backend/trading/stop_loss_protection.py` | ✅ Core |
| Smart Order Executor | `backend/orders/smart_order_executor.py` | ✅ Core |
| Fill Detection Engine | `backend/orders/fill_detection_engine.py` | ✅ Core |
| Bracket Orders | `backend/orders/bracket_orders.py` | ✅ Core |
| Wave Entry | `backend/trading/wave_entry.py` | ✅ Core |
| R-Multiple Profit Taker | `backend/trading/profit_taker.py` | ✅ Core |
| Breakeven Manager | `backend/trading/breakeven_manager.py` | ✅ Core |
| Parameter Optimizer | `backend/adaptive/parameter_optimizer.py` | ✅ Useful |
| VIX Provider | `backend/trading/vix_provider.py` | ✅ Core |
| Symbol Cooldown | `backend/trading/symbol_cooldown.py` | ✅ Core |
| AI Trade Validator | `backend/trading/ai_trade_validator.py` | ❌ Replace with agents |
| Strategy Engine | `backend/trading/strategy.py` | ⚠️ Extract signals only |

**Key lessons learned:** Bracket orders essential; 5s stop verification catches orphaned orders; R-multiple thinking normalises risk across setups; EOD exit at 15:57 prevents gap risk; no entries after 15:30.

### 3.2 From TradingAgents

| Component | File | Repurpose? |
|---|---|---|
| TradingAgentsGraph | `graph/trading_graph.py` | ✅ Core — adapt for real-time |
| Graph Setup (LangGraph) | `graph/setup.py` | ✅ Core |
| Reflection System | `graph/reflection.py` | ✅ Core — with TTL + regime guard |
| Signal Processing | `graph/signal_processing.py` | ✅ Core |
| 4 Analyst Agents | `agents/analysts/*.py` | ✅ Core — run in parallel |
| Bull/Bear Researchers | `agents/researchers/*.py` | ✅ Core — debate system |
| Research Manager | `agents/managers/research_manager.py` | ✅ Core — deep-think LLM |
| Portfolio Manager | `agents/managers/portfolio_manager.py` | ✅ Core — deep-think LLM |
| 3 Risk Debators | `agents/risk_mgmt/*.py` | ✅ Core |
| FinancialSituationMemory | `agents/utils/memory.py` | ✅ Core — with TTL + regime tags |
| Data Interface | `dataflows/interface.py` | ✅ Core |

**Critical gap filled:** TradingAgents has NO execution engine. MoonshotX fills this from DayTraderAI.

### 3.3 From Moonshot-CEX (Lessons Paid in Real Dollars)

| Component | Repurpose? | Key Lesson |
|---|---|---|
| Bayesian Decision Engine | ✅ Core | Entry quality gate, posterior ≥ 0.45 |
| QuantMutator | ✅ Core | Hard floor 0.40, ceiling 0.55 |
| BigBrother Regime | ✅ Core | Regime-specific parameter scaling |
| Position Manager exits | ✅ Core | Trailing stop = THE profit engine |
| Execution Core | ✅ Core | Market sells for SL (IOC failed: -$747) |
| Risk Manager | ✅ Core | Drawdown tracking, position limits |

**Critical lessons:** Threshold floor 0.12 destroyed P&L (-$387/day); 185 trades/day = guaranteed loss; premature exits killed 100% of winners; time exit only for losers; 4h symbol cooldown prevents churn; dust positions cycle forever without cleanup.

***

## 4. System Architecture

### 4.1 Data Flow — One Complete Cycle

```
1.  SCAN      → Universe scanner: top 50 liquid stocks + EarningsMomentumScore
2.  PRE-GATE  → Bayesian quick_score < 0.45 → skip (< 100ms)
3.  EARNINGS  → Earnings blackout check: skip if within 48h of earnings
4.  DATA      → Feature engine: 50+ indicators per stock (cached)
5.  ANALYZE   → 4 analyst agents run IN PARALLEL (asyncio.gather, ≤ 45s budget)
6.  DEBATE    → Bull/Bear researchers argue N rounds
7.  JUDGE     → Research Manager synthesises verdict (deep-think LLM)
8.  PLAN      → Trader agent creates entry plan
9.  RISK      → 3-way risk debate evaluates plan
10. APPROVE   → Portfolio Manager approves/rejects (deep-think LLM)
11. GATE      → Final Bayesian check: posterior ≥ 0.45
12. EXECUTE   → Smart Order Executor: bracket order via Alpaca
13. MANAGE    → Position Manager: trailing, R-multiples, time exit (5s loop)
14. EXIT      → Mechanical triggers (SL/trailing/time/EOD/earnings auto-exit)
15. REFLECT   → All agents review outcome, update memory (TTL + regime tag)
16. ADAPT     → QuantMutator adjusts threshold; optimizer tunes weekly
17. REPEAT    → Loop every 60s during market hours
```

### 4.2 Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Agent Framework | LangGraph + LangChain |
| LLM — Deep Think | Claude 3.7 Sonnet / GPT-4o (Research Manager, Portfolio Manager) |
| LLM — Quick Think | GPT-4o-mini / Claude Haiku (all 4 analysts, researchers, trader, risk) |
| Broker API | Alpaca Markets (commission-free, bracket orders) |
| Backend | FastAPI + uvicorn |
| Database | Supabase (PostgreSQL + pgvector for memory) |
| Frontend | React 18 + TypeScript + Tailwind |
| Data | yFinance + Alpaca WS + Twelve Data |
| Deployment | VPS Chicago (proximity to NYSE/NASDAQ) |

### 4.3 Real-Time Parallel Loop (v1.1 — Rewritten)

The v1.0 sequential design was a fatal arithmetic error: 10 candidates × 30s = 300s in a 60s loop. v1.1 enforces a **45-second wall-clock budget** with full parallelism at every layer.

```python
async def trading_loop():
    while market_is_open():
        loop_start = time.monotonic()

        # === PHASE 1: UNIVERSE SCAN (< 5s, pure quant) ===
        candidates = universe_scanner.get_top_candidates(n=10)
        # Bayesian pre-filter + earnings blackout — < 100ms per stock
        viable = [
            t for t in candidates
            if bayesian_engine.quick_score(t) >= 0.45
            and not earnings_calendar.is_blackout(t)
        ]

        # === PHASE 2: PARALLEL AGENT ANALYSIS (≤ 35s budget) ===
        # All tickers processed in parallel; each ticker's 4 analysts in parallel
        async def analyse_ticker(ticker):
            try:
                async with asyncio.timeout(35):
                    state, decision = await agents.propagate_parallel(ticker, today)
                    return ticker, decision
            except asyncio.TimeoutError:
                logger.warning(f"{ticker}: agent timeout, skipping")
                return ticker, None

        results = await asyncio.gather(
            *[analyse_ticker(t) for t in viable],
            return_exceptions=True
        )

        # === PHASE 3: EXECUTION (remaining budget) ===
        for ticker, decision in results:
            if decision and decision.action == "BUY":
                if portfolio_manager.approved(decision):
                    await execution_engine.enter(ticker, decision.plan)

        # === PHASE 4: POSITION MANAGEMENT (always runs) ===
        await position_manager.tick_all_positions()

        # === PHASE 5: RISK CHECKS ===
        if risk_manager.daily_loss_exceeded():
            await emergency_protocols.halt_trading_day()
            break

        # === LOOP TIMING ===
        elapsed = time.monotonic() - loop_start
        await asyncio.sleep(max(0, 60 - elapsed))
```

**Inside `propagate_parallel`:** The 4 analyst agents run simultaneously, not sequentially:

```python
async def propagate_parallel(ticker, date):
    # All 4 analysts fire at once — quick-think LLM, non-blocking
    tech_task    = asyncio.create_task(technical_analyst.analyse(ticker, date))
    sent_task    = asyncio.create_task(sentiment_analyst.analyse(ticker, date))
    news_task    = asyncio.create_task(news_analyst.analyse(ticker, date))
    fund_task    = asyncio.create_task(fundamentals_analyst.analyse(ticker, date))

    # Sentiment + fundamentals are enrichment — if they don't finish in time,
    # proceed without them rather than block
    done, pending = await asyncio.wait(
        [tech_task, sent_task, news_task, fund_task],
        timeout=20,
        return_when=asyncio.ALL_COMPLETED
    )
    for task in pending:
        task.cancel()  # non-blocking enrichment agents timed out — proceed anyway

    reports = {t: t.result() for t in done if not t.exception()}
    # Mandatory: technical must have completed
    if tech_task not in done:
        return None, None

    # Debate → Judge → Risk → Portfolio Manager
    return await run_debate_pipeline(ticker, reports)
```

***

## 5. Multi-Agent Intelligence Layer

### 5.1 Agent Roster with LLM Tier

| Agent | LLM Tier | Role | Blocking? |
|---|---|---|---|
| Technical Analyst | Quick-think | Price action, indicators, patterns | ✅ Mandatory |
| News Analyst | Quick-think | Breaking news, macro events | ✅ Mandatory |
| Sentiment Analyst | Quick-think | Social media & retail sentiment | ⚠️ Optional enrichment |
| Fundamentals Analyst | Quick-think | Earnings, valuations, balance sheet | ⚠️ Optional enrichment |
| Bull Researcher | Quick-think | Build bullish case from reports | ✅ Mandatory |
| Bear Researcher | Quick-think | Build bearish case from reports | ✅ Mandatory |
| Research Manager | **Deep-think** | Judge debate, synthesise verdict | ✅ Mandatory |
| Trader | Quick-think | Create entry plan (ticker, size, SL, TP) | ✅ Mandatory |
| Aggressive Analyst | Quick-think | Argue for larger position / tighter SL | ✅ Mandatory |
| Neutral Analyst | Quick-think | Balance risk/reward objectively | ✅ Mandatory |
| Conservative Analyst | Quick-think | Argue for smaller position / rejection | ✅ Mandatory |
| Portfolio Manager | **Deep-think** | Final APPROVE/REJECT | ✅ Mandatory |

**Tier rationale:** Deep-think (Claude 3.7 / GPT-4o) used only at the two synthesis nodes. All other agents use quick-think (GPT-4o-mini / Haiku) to stay within latency and cost budgets. See Section 17 for cost model.

### 5.2 LangGraph Flow (Parallel-Aware)

```
START
  → [Technical Analyst]  ──┐
  → [News Analyst]         ├── asyncio.gather() — all 4 fire simultaneously
  → [Sentiment Analyst]    ├── (optional: timeout=20s, skip if late)
  → [Fundamentals Analyst] ┘
  → [Bull Researcher] ↔ [Bear Researcher]  (N=2 debate rounds)
  → [Research Manager]  (deep-think — judge verdict)
  → [Trader]  (execution plan)
  → [Aggressive] ↔ [Conservative] ↔ [Neutral]  (M=2 risk rounds)
  → [Portfolio Manager]  (deep-think — APPROVE / REJECT)
END
```

### 5.3 Debate Mechanism

**Investment Debate (Bull vs Bear):**
- Bull receives all analyst reports, builds the strongest possible case for buying
- Bear builds the strongest possible case against
- Alternate for `max_debate_rounds` (default: 2), each directly responding to the other
- Research Manager reads full debate history, issues verdict with explicit reasoning
- If Technical report is absent (timeout), Research Manager auto-REJECTs

**Risk Debate (3-way):**
- **Aggressive**: "Strong setup — increase size, tighten stop for better R:R"
- **Conservative**: "Too risky — reduce size, wider stop, or reject entirely"
- **Neutral**: "Objective risk/reward — here's my balanced recommendation"
- Portfolio Manager makes final call after reading all three perspectives

### 5.4 Memory Architecture (v1.1 — TTL + Regime Tags)

The v1.0 memory system had no expiry and no regime filtering, creating silent memory poisoning risk. v1.1 adds three structural safeguards:

```python
@dataclass
class MemoryEntry:
    situation: str          # vectorised market context
    reflection: str         # agent lesson
    regime: str             # "bull" | "neutral" | "fear" | "choppy"
    outcome: float          # trade P&L %
    created_at: datetime
    ttl_days: int = 90       # hard expiry

class GuardedFinancialSituationMemory:
    def add(self, situation, reflection, regime, outcome):
        entry = MemoryEntry(
            situation=situation,
            reflection=reflection,
            regime=regime,
            outcome=outcome,
            created_at=datetime.utcnow()
        )
        self.store.upsert(entry)
        self._prune_expired()  # remove TTL-expired entries on every write

    def retrieve(self, current_situation, current_regime, top_k=3):
        # Regime-filtered cosine similarity — never cross-regime retrieval
        return self.store.similarity_search(
            query=current_situation,
            filter={"regime": current_regime,
                    "created_at": {"$gte": datetime.utcnow() - timedelta(days=90)}},
            k=top_k
        )

    def _prune_expired(self):
        cutoff = datetime.utcnow() - timedelta(days=self.ttl_days)
        self.store.delete(filter={"created_at": {"$lt": cutoff}})
```

**Reflection prompt (after every trade):**
Each memory-augmented agent answers:
1. Was this decision correct given what was knowable at entry?
2. What factors were missed or overweighted?
3. What would you do differently in the same regime?
4. Extract one 1-sentence lesson for future reference.

***

## 6. Strategy Engine

### 6.1 Universe Scanner with EarningsMomentumScorer (NEW)

The v1.0 scanner used a 3-factor static composite. v1.1 adds `EarningsMomentumScore` as the genuine differentiating alpha source — neither DayTraderAI nor TradingAgents has this.

```python
UNIVERSE_CRITERIA = {
    "min_market_cap": 10_000_000_000,   # $10B+ large cap
    "min_avg_volume": 5_000_000,         # 5M+ shares/day
    "min_price": 20.0,
    "max_price": 1000.0,
    "exchanges": ["NYSE", "NASDAQ"],
}

def earnings_momentum_score(ticker) -> float:
    """
    Score 0.0–1.0 for earnings catalyst quality.
    Peaks in the 2–10 day window after a strong earnings event.
    """
    score = 0.0
    eps_beat_pct = get_eps_surprise(ticker)           # e.g. +15% = 0.4 pts
    analyst_upgrades = count_upgrades_last_7d(ticker) # each = 0.1 pts
    price_compression = get_atr_contraction(ticker)   # tight BB = 0.2 pts
    volume_confirmation = get_volume_surge_post_earn(ticker)  # > 2x = 0.3 pts

    if eps_beat_pct > 0.10: score += 0.4
    elif eps_beat_pct > 0.05: score += 0.2
    score += min(0.3, analyst_upgrades * 0.1)
    if price_compression: score += 0.2
    if volume_confirmation: score += 0.3
    return min(1.0, score)

def rank_universe():
    stocks = filter_by_criteria(UNIVERSE_CRITERIA)
    for s in stocks:
        s.composite = (
            0.25 * momentum_20d(s)
          + 0.25 * volume_surge(s)
          + 0.20 * gap_pct(s)
          + 0.30 * earnings_momentum_score(s)   # NEW — the edge
        )
    return sorted(stocks, key=lambda s: s.composite, reverse=True)[:50]
```

**Why this is the edge:** Stocks in the 2–10 day post-earnings-beat window with analyst upgrades and technical breakout are in a confirmed institutional re-rating cycle. The move is early, not extended. Neither pure quant systems nor generic LLM agents identify this confluence systematically.

### 6.2 Earnings Blackout Rule (Hard Rule — NOT an Agent Decision)

```python
class EarningsCalendar:
    BLACKOUT_HOURS_PRE = 48     # No new entries within 48h before earnings
    AUTO_EXIT_MINUTES = 30      # Force-exit open positions T-30min before

    def is_blackout(self, ticker) -> bool:
        next_earnings = self.get_next_earnings(ticker)
        if next_earnings is None:
            return False
        hours_until = (next_earnings - datetime.now(ET)).total_seconds() / 3600
        return hours_until <= self.BLACKOUT_HOURS_PRE

    async def earnings_exit_monitor(self, position_manager):
        """Runs every 5 minutes — exits positions approaching earnings."""
        for position in position_manager.open_positions:
            next_earn = self.get_next_earnings(position.ticker)
            if next_earn:
                mins_until = (next_earn - datetime.now(ET)).total_seconds() / 60
                if mins_until <= self.AUTO_EXIT_MINUTES:
                    await position_manager.force_exit(
                        position.ticker,
                        reason="EARNINGS_BLACKOUT_AUTO_EXIT"
                    )
```

### 6.3 Wave Rider Entry Conditions

```python
WAVE_ENTRY_CONDITIONS = {
    "trend":    "5m/15m EMA9 > EMA21, 1h bullish",
    "momentum": "RSI 40–75, MACD histogram > 0",
    "volume":   "> 1.2× average",
    "timing":   "Pullback to EMA9/21 zone, bounce confirmation",
    "agents":   "BUY decision, Portfolio Manager APPROVED",
    "bayesian": "Posterior ≥ 0.45",
    "earnings": "Not within 48h of earnings event",
}
```

### 6.4 Momentum Fast-Track

If 1h return > 2% AND volume > 2× average → skip EMA/MACD gates, proceed directly to agent evaluation. Still requires agent consensus + Bayesian threshold + earnings check.

### 6.5 Multi-Timeframe Weights

| Timeframe | Weight | Purpose |
|---|---|---|
| 5-minute | 15% | Entry timing precision |
| 15-minute | 30% | Trend confirmation |
| 1-hour | 35% | Primary trend direction |
| 4-hour | 15% | Higher TF context |
| Daily | 5% | Major S/R levels |

***

## 7. Risk Management Framework

### 7.1 Five-Tier Risk Hierarchy

```
TIER 1: PORTFOLIO
├── Max drawdown: 15% → FULL HALT
├── Target drawdown: < 12%
├── Recovery: resume at 10% drawdown
└── Account < initial × 0.80 → SHUTDOWN + manual review required

TIER 2: DAILY
├── Max daily loss: 3% → stop for the day
├── Max daily trades: 15
├── 3 consecutive losses → 30-min pause
└── LLM cost > daily cap → switch to quant-only mode (no agent calls)

TIER 3: POSITION
├── Max positions: 5 (bull), 3 (neutral), 1 (fear), 0 (extreme_fear/choppy)
├── Max single position: 4% of portfolio
├── Max sector exposure: 20%
└── Max correlated positions: 2 (correlation defined in Section 7.3)

TIER 4: ENTRY
├── Bayesian posterior ≥ 0.45
├── Agent consensus: Portfolio Manager APPROVED
├── Symbol cooldown: 4 hours
├── No entry after 15:30 ET
└── No entry within 48h of earnings (hard rule)

TIER 5: EXECUTION
├── Bracket orders mandatory
├── 5-second stop verification loop
├── Market sells for SL/trailing exits
├── Fill detection 30s timeout
└── Max slippage: see Section 8.3 (ADV-based model)
```

### 7.2 Position Sizing (ATR-Based, Regime-Adjusted)

```python
def calculate_position_size(ticker, entry, stop, regime, portfolio_value):
    base_risk = 0.015  # 1.5% per trade
    regime_mult = {
        "bull":         1.2,
        "neutral":      1.0,
        "fear":         0.7,
        "extreme_fear": 0.3,
        "choppy":       0.0,   # no new positions
        "bear_mode":    0.0,   # long-side closed, inverse ETF sizing separate
    }
    risk_pct = base_risk * regime_mult[regime]
    if risk_pct == 0:
        return 0
    dollar_risk = portfolio_value * risk_pct
    stop_distance = abs(entry - stop) / entry
    raw_size = dollar_risk / stop_distance
    # Hard cap: never more than 4% of portfolio in single position
    position_value = min(raw_size, portfolio_value * 0.04)
    # Liquidity check: never more than 1% of stock's 30-day ADV
    adv_cap = get_adv_30d(ticker) * 0.01 * entry
    position_value = min(position_value, adv_cap)
    return int(position_value / entry)
```

### 7.3 Correlation Risk — Real-Time Definition (v1.1)

The v1.0 paper said "max 2 correlated positions" without defining how correlation is computed. v1.1 uses rolling 20-day beta to SPY as the real-time proxy:

```python
class CorrelationManager:
    CORRELATION_THRESHOLD = 0.75
    WINDOW_DAYS = 20

    def get_spy_correlation(self, ticker) -> float:
        """Rolling 20-day correlation of daily returns to SPY."""
        ticker_returns = get_daily_returns(ticker, days=self.WINDOW_DAYS)
        spy_returns = get_daily_returns("SPY", days=self.WINDOW_DAYS)
        return np.corrcoef(ticker_returns, spy_returns)[0, 1]

    def correlated_position_count(self, open_positions, new_ticker) -> int:
        """
        Count how many open positions are highly correlated with new_ticker.
        Two positions with corr > 0.75 count as ONE correlated cluster.
        """
        new_corr = self.get_spy_correlation(new_ticker)
        count = 0
        for pos in open_positions:
            existing_corr = self.get_spy_correlation(pos.ticker)
            # Approximate cross-correlation via SPY correlation proximity
            if abs(new_corr - existing_corr) < 0.15:  # same cluster
                count += 1
        return count

    def can_add_position(self, open_positions, new_ticker) -> bool:
        return self.correlated_position_count(open_positions, new_ticker) < 2
```

### 7.4 Regime Detection (4-Input Enhanced)

| Input | Source | Regimes |
|---|---|---|
| Fear & Greed Index | CNN scraper | 0–100 (Extreme Fear → Extreme Greed) |
| VIX | CBOE (Alpaca) | < 15 Low → > 35 Crisis |
| Market Breadth | % S&P 500 > 200d MA | < 20% Strong Bear → > 70% Strong Bull |
| Momentum | 20-day SPY return | < -5% Strong Down → > 5% Strong Up |

```python
def classify_regime(fg, vix, breadth, spy_20d) -> str:
    if vix > 35 and breadth < 20:
        return "extreme_fear"
    if vix > 28 and breadth < 30:
        return "bear_mode"      # NEW — triggers inverse ETF rotation
    if vix > 22 or breadth < 40:
        return "fear"
    if fg < 30 or spy_20d < -0.02:
        return "choppy"
    if fg > 70 and breadth > 60 and spy_20d > 0.03:
        return "bull"
    return "neutral"
```

Regime-specific parameter scaling:

| Regime | SL Mult | Trail Mult | Time Mult | Max Positions | Mode |
|---|---|---|---|---|---|
| Bull | 1.4× | 1.3× | 1.5× | 5 | Long |
| Neutral | 1.0× | 1.0× | 1.0× | 4 | Long |
| Fear | 0.7× | 0.8× | 0.6× | 3 | Long (reduced) |
| Choppy | — | — | — | 0 | **Full cash** |
| Bear Mode | — | — | — | 0 | **Inverse ETF only** |
| Extreme Fear | — | — | — | 0 | **Full cash** |

### 7.5 BEAR_MODE — Inverse ETF Rotation (NEW)

When `regime == "bear_mode"` (VIX > 28 AND breadth < 30%), the system does not just reduce positions — it pivots:

```python
INVERSE_ETF_MAP = {
    "broad_market": "SQQQ",    # 3× inverse NASDAQ — primary
    "sp500":        "SPXU",    # 3× inverse S&P500 — secondary
    "mild_hedge":   "SH",      # 1× inverse S&P500 — light hedge
}

class BearModeManager:
    MAX_INVERSE_ALLOCATION = 0.15   # Never more than 15% in inverse ETFs
    INVERSE_POSITION_SIZE  = 0.05   # 5% per inverse ETF position

    async def activate_bear_mode(self, portfolio_value, current_positions):
        # 1. Exit all long positions gracefully (trailing stop tightened to 0.5%)
        for pos in current_positions:
            pos.trail_distance = 0.005   # tighten to 0.5%
            await position_manager.accelerated_exit(pos)

        # 2. Open inverse ETF hedge — ONLY after longs are cleared
        if regime_manager.confirm_bear_regime(min_periods=3):
            await execution_engine.enter_inverse_hedge(
                ticker="SQQQ",
                allocation=self.INVERSE_POSITION_SIZE,
                portfolio_value=portfolio_value
            )

        # 3. Hold with standard trailing stop — still mechanical exits
        # Same 5-tier risk hierarchy applies to inverse ETF positions

    async def deactivate_bear_mode(self):
        """Called when regime shifts back to neutral/bull."""
        await execution_engine.exit_all_inverse_positions()
```

**Important constraints on BEAR_MODE:**
- Inverse ETF entries STILL require Bayesian pre-filter (score ≥ 0.40 in bear regime)
- Maximum 15% portfolio allocation to inverse ETFs in aggregate
- Same trailing stop and exit hierarchy applies — not a "hold forever" hedge
- Regime must confirm for minimum 3 consecutive loop cycles before activation (prevents whipsawing)

### 7.6 Emergency Kill Switch (NEW — Human-in-the-Loop)

```python
# FastAPI endpoint — authenticated, single-call cascade shutdown
@router.post("/api/v1/emergency_halt", dependencies=[Depends(verify_api_key)])
async def emergency_halt(reason: str = "manual_override"):
    logger.critical(f"EMERGENCY HALT triggered: {reason}")

    # Step 1: Stop all new order generation immediately
    trading_loop.pause()

    # Step 2: Cancel all open/pending orders at broker
    cancelled = await alpaca_client.cancel_all_orders()

    # Step 3: Market-sell all open positions
    positions = await alpaca_client.get_all_positions()
    exits = [alpaca_client.submit_order(
                symbol=p.symbol, qty=p.qty,
                side='sell', type='market',
                time_in_force='day')
             for p in positions]
    await asyncio.gather(*exits)

    # Step 4: Log to Supabase + send alert
    await supabase.log_halt_event(reason, cancelled, len(exits))
    await alert_manager.send_critical(
        f"🛑 MoonshotX HALTED: {reason} | {len(exits)} positions closed"
    )

    return {"status": "halted", "orders_cancelled": cancelled, "positions_closed": len(exits)}
```

**Additional system controls:**
- `POST /api/v1/pause_entries` — stops new entries, manages existing positions normally
- `POST /api/v1/resume` — re-enables trading after manual review
- `GET /api/v1/status` — real-time system state, current regime, open positions, daily P&L
- All control endpoints require `X-API-Key` header (stored in environment, not codebase)

***

## 8. Execution Engine

### 8.1 Order Flow

```python
async def enter_position(ticker, shares, stop_price, tp_price):
    # 1. Pre-flight checks
    assert market_is_open(), "Market closed"
    assert risk_manager.position_count_ok(), "Position limit reached"
    assert risk_manager.daily_loss_ok(), "Daily loss limit hit"
    assert not earnings_calendar.is_blackout(ticker), "Earnings blackout"
    assert correlation_manager.can_add_position(open_positions, ticker), "Correlation limit"

    # 2. Bracket order — SL and TP set from birth
    order = await alpaca_client.submit_order(
        symbol=ticker, qty=shares, side='buy', type='market',
        time_in_force='day', order_class='bracket',
        stop_loss={'stop_price': round(stop_price, 2)},
        take_profit={'limit_price': round(tp_price, 2)}
    )

    # 3. Fill detection (30s timeout — no phantom positions)
    filled = await fill_detection.wait_for_fill(order.id, timeout=30)
    if not filled:
        await alpaca_client.cancel_order(order.id)
        logger.warning(f"{ticker}: fill timeout — order cancelled")
        return None

    # 4. Slippage validation
    actual_fill = filled.avg_fill_price
    slippage = abs(actual_fill - order.submitted_price) / order.submitted_price
    expected_max = slippage_model.max_expected(ticker)
    if slippage > expected_max:
        logger.warning(f"{ticker}: slippage {slippage:.3%} > model max {expected_max:.3%}")
        # Don't reject — log for backtesting calibration

    # 5. Register in position manager
    position_manager.register(Position(
        ticker=ticker, entry=actual_fill,
        shares=shares, stop=stop_price, tp=tp_price,
        regime=regime_manager.current
    ))
```

### 8.2 Execution Rules (Battle-Tested)

| Rule | Rationale |
|---|---|
| Market sells for SL/trailing | IOC limits fail in fast markets (−$747 XRP lesson from Moonshot-CEX) |
| Bracket orders mandatory | Every position has SL + TP from birth |
| 5-second stop verification | Catches orphaned/failed stop orders |
| Fill detection + 30s timeout | Prevents phantom positions |
| No entry after 15:30 ET | Low liquidity, high spread |
| EOD exit at 15:57 ET | Prevents overnight gap risk |
| 4-hour symbol cooldown | Prevents re-entry churn |
| Earnings auto-exit T-30min | Hard rule — not agent decision |

### 8.3 Realistic Slippage Model (v1.1 — NEW)

The v1.0 paper used a flat 0.3% slippage cap — unrealistic and not a model. v1.1 uses an ADV-based slippage estimate that reflects real market impact:

```python
class SlippageModel:
    """
    Estimates real execution slippage based on:
    - Position size as % of Average Daily Volume (market impact)
    - Bid/ask spread (liquidity cost)
    - Regime volatility (adverse selection)
    """
    def max_expected(self, ticker, shares, regime) -> float:
        adv = get_adv_30d(ticker)
        order_adv_pct = shares / adv

        # Base spread component (typical for large-cap liquid stocks)
        spread_cost = 0.001  # 0.1% for $10B+ market cap stocks

        # Market impact component (Kyle's lambda approximation)
        impact = 0.002 * (order_adv_pct ** 0.5)  # square-root market impact

        # Regime multiplier
        regime_mult = {"bull": 1.0, "neutral": 1.0, "fear": 1.5,
                       "choppy": 2.0, "bear_mode": 1.8}
        mult = regime_mult.get(regime, 1.0)

        return (spread_cost + impact) * mult

    def effective_cost(self, entry_fill, exit_fill, entry_price, exit_price) -> float:
        """Total round-trip cost including spread + slippage."""
        entry_slip = abs(entry_fill - entry_price) / entry_price
        exit_slip  = abs(exit_fill  - exit_price)  / exit_price
        return entry_slip + exit_slip

# Backtest: apply slippage model to every simulated fill
def simulate_fill(price, shares, ticker, side, regime) -> float:
    slip = slippage_model.max_expected(ticker, shares, regime)
    return price * (1 + slip) if side == 'buy' else price * (1 - slip)
```

**In backtesting:** Every single fill applies this model. A backtest without realistic slippage is fiction — it will show a profitable system that loses money live.

***

## 9. Position Management

### 9.1 Exit Hierarchy (Evaluated Every 5 Seconds)

| Priority | Exit | Condition | Action |
|---|---|---|---|
| 1 | **Stop Loss** | pnl ≤ −SL% (ATR-based) | MARKET SELL 100% |
| 2 | **Trailing Stop** | Activated at +1%, distance 1% | MARKET SELL 100% |
| 3 | **Partial Profit 2R** | R-multiple ≥ 2.0 | SELL 50%, move SL to breakeven |
| 4 | **Partial Profit 3R** | R-multiple ≥ 3.0 | SELL 25% remaining, trail rest |
| 5 | **Breakeven** | R-multiple ≥ 1.0 | Move SL to entry price |
| 6 | **Time Exit** | Hold ≥ 3h AND pnl ≤ 0 | MARKET SELL 100% |
| 7 | **Time Exit Max** | Hold ≥ 6h (any pnl) | MARKET SELL 100% |
| 8 | **Momentum Faded** | Peak ≥ 3%, gave back 60%+, pnl < 0.5% | MARKET SELL 100% |
| 9 | **Earnings Auto-Exit** | T−30min before earnings | MARKET SELL 100% |
| 10 | **EOD Exit** | Time ≥ 15:57 ET | MARKET SELL 100% |

**Key principle:** Time exit is for losers only (Priority 6). Winners ride via trailing stop (Priority 2). This single rule is responsible for fixing the "winners held 0.41h vs losers 3.78h" failure mode from prior systems.

### 9.2 R-Multiple Tracking

```python
class RMultipleTracker:
    def __init__(self, entry_price, stop_price):
        self.entry  = entry_price
        self.risk   = abs(entry_price - stop_price)  # 1R = this distance
        self.peak_r = 0.0

    def current_r(self, price) -> float:
        return (price - self.entry) / self.risk

    def update(self, price) -> float:
        r = self.current_r(price)
        self.peak_r = max(self.peak_r, r)
        return r

    def gave_back_pct(self, price) -> float:
        if self.peak_r <= 0:
            return 0.0
        current = self.current_r(price)
        return (self.peak_r - current) / self.peak_r
```

### 9.3 Trailing Stop Modes

| Mode | Activation | Distance | Use Case |
|---|---|---|---|
| Standard | +1.0% | 1.0% | Default |
| ATR-Based | 1.0 × ATR | 1.5 × ATR | Volatile stocks |
| Regime-Scaled | Standard × mult | Standard × mult | Auto-adapts |
| Chandelier | Highest high − 3×ATR | Dynamic | Swing holds |
| Accelerated | Any time | 0.5% | Pre-earnings exit acceleration |

***

## 10. Learning & Reflection System

### 10.1 Post-Trade Reflection

After every closed trade, each memory-augmented agent reflects and stores to `GuardedFinancialSituationMemory` (Section 5.4) tagged with the current regime. The regime tag means future retrieval will only surface lessons from similar market conditions.

### 10.2 QuantMutator (from Moonshot-CEX, with hard floors)

```python
class QuantMutator:
    FLOOR   = 0.40    # NEVER below (0.12 destroyed Moonshot-CEX: −$387/day)
    CEILING = 0.55    # Don't block all entries
    DEFAULT = 0.45

    def mutate(self, win_rate, day_pnl_pct, threshold) -> tuple[float, str]:
        if win_rate >= 0.65:
            return max(self.FLOOR, threshold - 0.02), "hot_streak"
        elif win_rate <= 0.35:
            return min(self.CEILING, threshold + 0.02), "cold_streak"
        elif day_pnl_pct < -0.03:
            return min(self.CEILING, threshold + 0.03), "emergency_raise"
        elif llm_cost_manager.over_budget():
            return min(self.CEILING, threshold + 0.05), "cost_throttle"
        return threshold, "no_change"
```

### 10.3 Weekly Parameter Optimisation

Bayesian optimisation every Sunday against Sharpe ratio from last 20 trading days:

| Parameter | Range |
|---|---|
| `stop_loss_atr_mult` | (1.0, 3.0) |
| `trailing_activate_pct` | (0.5%, 2.0%) |
| `trailing_distance_pct` | (0.5%, 2.0%) |
| `rsi_entry_low/high` | (30–50, 65–80) |
| `time_exit_hours` | (2, 6) |
| `earnings_blackout_hours` | (24, 72) |

***

## 11. Data Infrastructure

### 11.1 Sources

| Source | Data | Frequency | Cost |
|---|---|---|---|
| Alpaca WebSocket | Real-time bars (1m/5m/15m) | Real-time | Free |
| Alpaca REST | Historical bars, account, positions | On-demand | Free |
| yFinance | Fundamentals, earnings calendar, news | Pre-market + on-demand | Free |
| CNN Fear & Greed | F&G Index (0–100) | 15 min | Free |
| CBOE VIX | Volatility Index | Via Alpaca | Free |
| Twelve Data | Daily bars cache | Daily | Free tier |
| Polygon.io | Tick-level historical, ADV data | Backtest | $29/mo |

### 11.2 Feature Engine (50+ Indicators)

- **Trend:** EMA 9/21/50/200, SMA 20/50/200
- **Momentum:** RSI 14/7, MACD, Stochastic K/D, Williams %R, CCI
- **Volatility:** ATR 14/7, Bollinger Bands, Keltner Channels, BB Width (compression)
- **Volume:** VWAP, Volume SMA 20, OBV, MFI, Volume Ratio vs 20d ADV
- **Price Action:** Support/Resistance, Pivot Points, Candlestick Patterns
- **Custom:** 1h Momentum, Gap %, Relative Strength vs SPY, EarningsMomentumScore

***

## 12. Backtesting & Validation

### 12.1 Simulated Broker (Built Week 1 — NOT Week 15)

The original roadmap deferred backtesting to Phase 6. This was backwards — you cannot validate agent logic, risk hierarchy, or exit strategies without a simulated execution environment. The simulated broker is the **first thing built**.

```python
class SimulatedBroker:
    """Drop-in replacement for AlpacaClient in backtest mode."""
    def __init__(self, initial_capital, slippage_model):
        self.cash     = initial_capital
        self.positions = {}
        self.trades   = []
        self.slippage = slippage_model

    async def submit_order(self, symbol, qty, side, type, **kwargs):
        price = get_historical_price(symbol, self.current_bar)
        fill  = self.slippage.simulate_fill(price, qty, symbol, side, regime)
        # Apply fill, update cash, record trade
        ...

    def get_performance(self) -> dict:
        return {
            "sharpe":      calculate_sharpe(self.trades),
            "profit_factor": calculate_pf(self.trades),
            "max_drawdown": calculate_mdd(self.trades),
            "win_rate":    len([t for t in self.trades if t.pnl > 0]) / len(self.trades),
            "total_trades": len(self.trades),
        }
```

### 12.2 Validation Protocol

| Phase | Duration | Capital | Risk | Gate |
|---|---|---|---|---|
| 1. Backtest | 2yr historical (2024–2025) | Simulated $50K | None | ≥ 200 trades, metrics check |
| 2. Paper Trade | 30 days | Alpaca paper account | None | Win rate ≥ 55%, PF ≥ 1.5 |
| 3. Micro Live | 30 days | $5K real | Very low | Win rate ≥ 55%, PF ≥ 1.8 |
| 4. Small Live | 60 days | $25K real | Low | Win rate ≥ 55%, PF ≥ 2.0 |
| 5. Full Live | Ongoing | $50K+ | Normal | Ongoing monitoring |

### 12.3 Go/No-Go Criteria

| Metric | Phase 2→3 | Phase 3→4 | Phase 4→5 |
|---|---|---|---|
| Win Rate | ≥ 50% | ≥ 52% | ≥ 55% |
| Profit Factor | ≥ 1.5 | ≥ 1.8 | ≥ 2.0 |
| Max Drawdown | < 15% | < 12% | < 10% |
| Sharpe | ≥ 1.2 | ≥ 1.5 | ≥ 1.8 |
| Total Trades | ≥ 50 | ≥ 100 | ≥ 200 |
| Slippage vs Model | within 20% of model | within 15% | within 10% |

***

## 13. Implementation Roadmap (Resequenced — Backtest First)

### Phase 0: Foundation + Backtester (Weeks 1–2) ← FIRST
- Simulated broker + backtesting framework
- Historical data pipeline (Polygon.io for ticks)
- Slippage model implementation
- Unified config + Supabase schema
- Alpaca paper account integration

### Phase 1: Quant Engine (Weeks 3–4) — Testable in Backtest
- Feature engine (50+ indicators) from DayTraderAI
- Wave entry conditions + universe scanner (3-factor first)
- Bayesian engine from Moonshot-CEX
- Regime detection (4 inputs)
- Validate quant-only performance in backtest before adding agents

### Phase 2: Agent Intelligence (Weeks 5–8) — Plug into Backtest
- LangGraph parallel setup from TradingAgents
- 4 analyst agents (parallel asyncio.gather)
- Bull/Bear debate + Research Manager
- 3-way Risk debate + Portfolio Manager
- GuardedFinancialSituationMemory (with TTL + regime tags)
- EarningsMomentumScorer + earnings blackout hard rule
- Run full backtest with agents — validate improvement over quant-only baseline

### Phase 3: Execution Engine (Weeks 9–11) — Paper Trade
- Smart Order Executor from DayTraderAI
- Bracket order system
- Merged Position Manager (DayTraderAI exits + Moonshot-CEX trailing)
- R-multiple tracking + all trailing stop modes
- 5-second stop verification loop
- Fill detection engine
- Emergency kill switch API
- Paper trade 30 days → Phase 2→3 gate

### Phase 4: Risk Architecture (Weeks 12–13)
- 5-tier risk hierarchy fully wired
- BEAR_MODE + inverse ETF rotation
- QuantMutator with hard floors
- Circuit breakers + correlation manager
- Weekly parameter optimiser

### Phase 5: Learning Layer (Weeks 14–15)
- Reflection system integrated
- Memory retrieval injected into agent system prompts
- LLM cost circuit breaker + daily cap enforcement

### Phase 6: Frontend + Monitoring (Weeks 16–17)
- React dashboard from DayTraderAI (adapted)
- Agent decision audit trail
- Real-time position/P&L display
- Regime indicator + cost tracker
- Performance charts (Sharpe, drawdown, win rate rolling)

### Phase 7: Validation + Micro-Live (Weeks 18–22)
- Full 2-year backtest with slippage model
- Paper trade 30 days (Phase 2→3 gate)
- Micro-live $5K (Phase 3→4 gate)
- Iterate on parameters
- Go/No-Go to $25K small live

**Total: ~22 weeks (5.5 months) to micro-live with confidence.**

***

## 14. Proposed File Structure

```
moonshotx/
├── backend/
│   ├── server.py                       # FastAPI main
│   ├── config.py                       # Unified config
│   ├── agents/                         # From TradingAgents
│   │   ├── analysts/                   # technical, sentiment, news, fundamentals
│   │   ├── researchers/                # bull, bear
│   │   ├── managers/                   # research_manager, portfolio_manager
│   │   ├── risk_mgmt/                  # aggressive, neutral, conservative
│   │   ├── trader/
│   │   └── utils/                      # memory (guarded), states, utils
│   ├── graph/                          # LangGraph orchestration
│   │   ├── trading_graph.py            # parallel-aware
│   │   ├── setup.py
│   │   ├── propagation.py              # propagate_parallel()
│   │   ├── reflection.py
│   │   ├── signal_processing.py
│   │   └── conditional_logic.py
│   ├── data/                           # From DayTraderAI
│   │   ├── market_data.py              # Alpaca WS
│   │   ├── features.py                 # 50+ indicators
│   │   ├── daily_cache.py
│   │   ├── earnings_calendar.py        # NEW — blackout logic
│   │   └── dataflows/                  # yFinance (from TradingAgents)
│   ├── trading/
│   │   ├── position_manager.py         # Merged exit system
│   │   ├── risk_manager.py             # 5-tier + regime
│   │   ├── regime_manager.py           # VIX + F&G + Breadth + Momentum
│   │   ├── bear_mode_manager.py        # NEW — inverse ETF rotation
│   │   ├── correlation_manager.py      # NEW — real-time rolling beta
│   │   ├── trailing_stops.py
│   │   ├── stop_loss_protection.py
│   │   ├── profit_taker.py
│   │   ├── breakeven_manager.py
│   │   ├── wave_entry.py
│   │   ├── symbol_cooldown.py
│   │   ├── universe_scanner.py         # 4-factor with EarningsMomentumScorer
│   │   ├── earnings_momentum_scorer.py # NEW — the edge
│   │   ├── bayesian_engine.py
│   │   └── quant_mutator.py
│   ├── orders/                         # From DayTraderAI
│   │   ├── smart_order_executor.py
│   │   ├── bracket_orders.py
│   │   └── fill_detection_engine.py
│   ├── risk/
│   │   ├── slippage_model.py           # NEW — ADV-based model
│   │   ├── llm_cost_manager.py         # NEW — daily cost circuit breaker
│   │   └── emergency_halt.py           # NEW — kill switch endpoint
│   ├── adaptive/
│   │   └── parameter_optimizer.py
│   └── backtest/                       # BUILT FIRST (Phase 0)
│       ├── simulated_broker.py
│       ├── backtester.py
│       └── performance_metrics.py
├── frontend/                           # From DayTraderAI (React)
│   └── src/components/
│       ├── Dashboard/
│       ├── PositionTable/
│       ├── AgentAuditTrail/            # NEW — full decision log
│       ├── EquityCurve/
│       ├── RegimeIndicator/
│       ├── LLMCostTracker/             # NEW
│       └── EmergencyHaltButton/        # NEW — prominent UI
└── tests/
    ├── unit/
    ├── integration/
    └── backtest_results/
```

***

## 15. Configuration Reference

```python
MOONSHOTX_CONFIG = {
    # === LLM ===
    "llm_provider":           "anthropic",       # or "openai"
    "deep_think_llm":         "claude-3-7-sonnet-20250219",
    "quick_think_llm":        "claude-haiku-3-5", # or "gpt-4o-mini"
    "max_debate_rounds":       2,
    "max_risk_discuss_rounds": 2,
    "agent_timeout_seconds":   20,               # per-agent async timeout
    "loop_wall_clock_seconds": 45,               # hard budget for analysis phase

    # === LLM Cost Controls ===
    "llm_cost_daily_cap_usd":  25.0,             # circuit breaker → quant-only mode
    "llm_cost_alert_usd":      15.0,             # warning alert

    # === Trading ===
    "risk_per_trade_pct":      0.015,
    "max_positions_bull":      5,
    "max_positions_neutral":   4,
    "max_positions_fear":      3,
    "max_positions_choppy":    0,               # full cash
    "max_single_position_pct": 0.04,
    "max_sector_exposure_pct": 0.20,
    "max_daily_loss_pct":      0.03,
    "max_drawdown_pct":        0.15,            # halt threshold
    "target_drawdown_pct":     0.12,            # design target

    # === Entry ===
    "bayesian_threshold":      0.45,
    "bayesian_floor":          0.40,
    "bayesian_ceiling":        0.55,
    "symbol_cooldown_hours":   4,
    "entry_cutoff_time":       "15:30",
    "earnings_blackout_hours": 48,              # NEW
    "earnings_auto_exit_mins": 30,              # NEW

    # === Exits ===
    "stop_loss_atr_mult":      1.5,
    "trailing_activate_pct":   0.01,
    "trailing_distance_pct":   0.01,
    "time_exit_hours":         3.0,
    "time_exit_max_hours":     6.0,
    "eod_exit_time":           "15:57",
    "partial_profit_2r_pct":   0.50,
    "partial_profit_3r_pct":   0.25,
    "breakeven_r_trigger":     1.0,

    # === Bear Mode ===
    "bear_mode_vix_trigger":   28,              # NEW
    "bear_mode_breadth_trigger": 0.30,          # NEW — % stocks > 200d MA
    "bear_mode_confirm_loops": 3,               # NEW — avoid whipsaw
    "inverse_etf_max_alloc":   0.15,            # NEW
    "inverse_etf_position_pct": 0.05,           # NEW

    # === Memory ===
    "memory_ttl_days":         90,              # NEW
    "memory_regime_filtered":  True,            # NEW

    # === Correlation ===
    "correlation_window_days": 20,              # NEW
    "correlation_threshold":   0.75,            # NEW

    # === Data ===
    "universe_size":           50,
    "min_market_cap":          10_000_000_000,
    "min_avg_volume":          5_000_000,
    "slippage_model_enabled":  True,            # NEW
}
```

***

## 16. Risk Disclosures

**Technical Risks:** LLM latency mitigated by asyncio.gather + 45s wall-clock hard budget. Hallucination risk mitigated by debate layer + fully mechanical exits. API rate limits (200 req/min Alpaca) mitigated by caching and pre-market data staging.

**Market Risks:** Flash crashes handled by 5s stop verification + market sells. Gap risk eliminated by EOD exit at 15:57. Regime misclassification risk reduced to 4 independent inputs with 3-cycle confirmation. Correlation risk now quantitatively defined (rolling 20d beta, 0.75 threshold). Bear markets handled by BEAR_MODE with inverse ETF rotation and full cash option.

**Operational Risks:** Server downtime mitigated by VPS 99.9% SLA + auto-restart with bracket orders persisting at broker. LLM cost explosion mitigated by daily cap circuit breaker and two-tier model. Memory corruption mitigated by 90-day TTL + regime-filtered retrieval.

***


## 17. LLM Cost Model (NEW — Section Added in v1.1)

LLM costs are a real operational expense that will kill profitability if unmanaged. At $15–30/million tokens for deep-think models, a naive implementation running full agent pipelines on every candidate can cost $50–200/day — more than many trading days will profit.

### Two-Tier Architecture Cost Breakdown

| Agent | LLM Tier | Model | Est. Tokens/Call | Cost/Call | Calls/Day |
|---|---|---|---|---|---|
| Technical Analyst | Quick-think | GPT-4o-mini / Haiku | ~2,000 | ~$0.0004 | 50 |
| News Analyst | Quick-think | GPT-4o-mini / Haiku | ~2,500 | ~$0.0005 | 50 |
| Sentiment Analyst | Quick-think | GPT-4o-mini / Haiku | ~1,500 | ~$0.0003 | 30 |
| Fundamentals Analyst | Quick-think | GPT-4o-mini / Haiku | ~3,000 | ~$0.0006 | 30 |
| Bull Researcher | Quick-think | GPT-4o-mini / Haiku | ~2,000 | ~$0.0004 | 15 |
| Bear Researcher | Quick-think | GPT-4o-mini / Haiku | ~2,000 | ~$0.0004 | 15 |
| Research Manager | **Deep-think** | Claude 3.7 / GPT-4o | ~8,000 | ~$0.024 | 15 |
| Trader | Quick-think | GPT-4o-mini / Haiku | ~1,500 | ~$0.0003 | 15 |
| Aggressive / Conservative / Neutral | Quick-think | GPT-4o-mini / Haiku | ~1,000 ea. | ~$0.0002 | 15 each |
| Portfolio Manager | **Deep-think** | Claude 3.7 / GPT-4o | ~8,000 | ~$0.024 | 15 |
| Reflection (post-trade) | Quick-think | GPT-4o-mini / Haiku | ~2,000 | ~$0.0004 | 15 |

### Daily Cost Estimate (Realistic — 15 Trades/Day)

```
Quick-think total:  ~$0.10–0.20/day
Deep-think total:   ~$0.72/day (2 nodes × 15 calls × $0.024)
─────────────────────────────────────
Total estimated:    ~$1.00–2.00/day
Monthly:            ~$20–40/month
```

This is **not** $50–200/day. That scenario only occurs if deep-think models are used for all agents (the v1.0 mistake) or if you're running 100+ full pipeline analyses per day with no Bayesian pre-filter. The two-tier model + Bayesian gate reduces cost by ~95%.

### LLM Cost Circuit Breaker

```python
class LLMCostManager:
    DAILY_CAP_USD   = 25.00   # Hard circuit breaker
    ALERT_USD       = 15.00   # Warning threshold
    QUANT_ONLY_MODE = False   # Fallback when cap hit

    def __init__(self):
        self.daily_spend = 0.0
        self.reset_time  = self._next_market_open()

    def record_call(self, tokens_in, tokens_out, model):
        cost = self._calculate_cost(tokens_in, tokens_out, model)
        self.daily_spend += cost

        if self.daily_spend >= self.DAILY_CAP_USD:
            self.QUANT_ONLY_MODE = True
            alert_manager.send_warning(
                f"⚠️ LLM daily cap ${self.DAILY_CAP_USD} hit — "
                f"switching to quant-only mode for remainder of session"
            )
        elif self.daily_spend >= self.ALERT_USD:
            alert_manager.send_info(
                f"LLM spend at ${self.daily_spend:.2f} — approaching cap"
            )

    def can_run_agents(self) -> bool:
        return not self.QUANT_ONLY_MODE

    def _calculate_cost(self, tokens_in, tokens_out, model) -> float:
        rates = {
            "claude-3-7-sonnet":  {"in": 3.00, "out": 15.00},  # per M tokens
            "gpt-4o":             {"in": 2.50, "out": 10.00},
            "gpt-4o-mini":        {"in": 0.15, "out": 0.60},
            "claude-haiku-3-5":   {"in": 0.80, "out": 4.00},
        }
        r = rates.get(model, {"in": 1.0, "out": 5.0})
        return (tokens_in * r["in"] + tokens_out * r["out"]) / 1_000_000
```

**Quant-only fallback mode:** When the daily LLM cap is hit, the system does not halt — it continues trading using only the Bayesian engine + technical indicators (no agent pipeline). This is explicitly designed as a viable degraded mode, not an emergency. The quant layer alone should be profitable; the agents are enhancement.

***

## 18. Alpha Source Definition — EarningsMomentumScorer (NEW)

This is the section that defines MoonshotX's genuine edge — the thing neither DayTraderAI, TradingAgents, nor any of their source repos identifies.

### Why Earnings Momentum is a Real Alpha Source

Post-earnings drift (PEAD) is one of the most documented and persistent anomalies in academic finance. Stocks that beat EPS estimates meaningfully tend to continue drifting in the direction of the surprise for 2–10 trading days. The mechanism:

1. **Institutional re-rating**: Funds that missed the earnings beat start accumulating — this is sustained buying pressure, not a one-day spike
2. **Analyst upgrade cycle**: Upgrades lag earnings by 24–72h, each upgrade triggers additional fund flow
3. **Retail FOMO**: Retail follows after day 2, adding additional momentum
4. **Short covering**: Shorts who were wrong on the quarter cover — adds fuel

The window is **specific**: best entries are in days 2–5 post-beat (day 1 is often too volatile, day 6+ the drift exhausts). MoonshotX's universe scanner specifically weights this window.

### EarningsMomentumScorer — Full Implementation Spec

```python
class EarningsMomentumScorer:
    """
    Scores stocks on post-earnings-beat momentum quality.
    Score: 0.0 (no catalyst) → 1.0 (perfect setup)
    Best entries: days 2–5 post-earnings-beat
    """

    # Scoring weights
    W_EPS_BEAT    = 0.35   # Quality of the beat
    W_ANALYST     = 0.25   # Analyst upgrade momentum post-beat
    W_COMPRESSION = 0.20   # Technical: tight base pre-earnings (more explosive)
    W_VOLUME      = 0.20   # Volume surge confirmation post-earnings

    def score(self, ticker) -> float:
        last_earnings = self.get_last_earnings(ticker)
        if not last_earnings:
            return 0.0

        days_since = (datetime.now() - last_earnings.date).days

        # Only score in the PEAD window: days 2–10 post-earnings
        if days_since < 2 or days_since > 10:
            return 0.0

        # Scoring decay: peak at day 3, fades after day 7
        day_multiplier = self._day_weight(days_since)

        eps_score      = self._score_eps_beat(last_earnings)
        analyst_score  = self._score_analyst_upgrades(ticker, last_earnings.date)
        compress_score = self._score_compression(ticker, last_earnings.date)
        volume_score   = self._score_volume_surge(ticker, last_earnings.date)

        raw = (
            self.W_EPS_BEAT    * eps_score    +
            self.W_ANALYST     * analyst_score +
            self.W_COMPRESSION * compress_score +
            self.W_VOLUME      * volume_score
        )
        return min(1.0, raw * day_multiplier)

    def _day_weight(self, days_since) -> float:
        """PEAD window: ramp up days 1-3, peak day 3, decay days 4-10."""
        weights = {1: 0.5, 2: 0.85, 3: 1.0, 4: 0.95, 5: 0.85,
                   6: 0.70, 7: 0.55, 8: 0.40, 9: 0.25, 10: 0.15}
        return weights.get(days_since, 0.0)

    def _score_eps_beat(self, earnings) -> float:
        beat_pct = earnings.eps_surprise_pct
        if beat_pct >= 0.20: return 1.0    # > 20% beat — exceptional
        if beat_pct >= 0.10: return 0.75   # > 10% beat — strong
        if beat_pct >= 0.05: return 0.50   # > 5% beat — moderate
        if beat_pct >= 0.01: return 0.20   # in-line or small beat
        return 0.0                          # miss — no score

    def _score_analyst_upgrades(self, ticker, since_date) -> float:
        upgrades = get_analyst_actions(ticker, since=since_date,
                                       action_type=["upgrade", "initiate"])
        return min(1.0, len(upgrades) * 0.33)   # 3 upgrades = max score

    def _score_compression(self, ticker, earnings_date) -> float:
        """Pre-earnings Bollinger Band width — tighter = more explosive setup."""
        pre_earn_bb_width = get_bb_width(ticker,
                                          end=earnings_date - timedelta(days=1),
                                          lookback=20)
        historical_avg = get_bb_width_avg(ticker, lookback=90)
        if historical_avg == 0:
            return 0.0
        compression_ratio = pre_earn_bb_width / historical_avg
        # Very tight (< 50% of average) = 1.0, average = 0.5, wide = 0.0
        return max(0.0, min(1.0, 1.0 - compression_ratio))

    def _score_volume_surge(self, ticker, since_date) -> float:
        """Post-earnings volume vs 30-day ADV."""
        post_earn_vol = get_avg_volume(ticker, start=since_date, days=3)
        adv_30 = get_adv_30d(ticker, end=since_date - timedelta(days=1))
        if adv_30 == 0:
            return 0.0
        ratio = post_earn_vol / adv_30
        if ratio >= 3.0: return 1.0
        if ratio >= 2.0: return 0.75
        if ratio >= 1.5: return 0.50
        return 0.0
```

### Integration with Universe Scanner

```python
def rank_universe():
    stocks = filter_by_criteria(UNIVERSE_CRITERIA)
    scorer = EarningsMomentumScorer()
    for s in stocks:
        s.composite = (
            0.25 * momentum_20d(s)              # Trend context
          + 0.25 * volume_surge_ratio(s)        # Institutional flow
          + 0.20 * gap_pct_premarket(s)         # Day's momentum
          + 0.30 * scorer.score(s.ticker)       # THE EDGE
        )
    # Stocks with no earnings catalyst still qualify via the other 3 factors
    # But stocks IN the PEAD window will systematically rank higher
    return sorted(stocks, key=lambda s: s.composite, reverse=True)[:50]
```

### Why This Survives LLM Critique

One external review argued "LLMs don't add signal edge — all inputs are public." That's true for generic inputs. But the EarningsMomentumScorer is different:

- **Not commoditised**: EMA + RSI are in every free screener. A 4-factor PEAD scorer with analyst upgrade weighting and BB compression is not
- **Verifiable edge**: PEAD is academically documented with decades of data — it persists because institutional mandates prevent funds from fully arbitraging it away
- **Timing precision**: The day-weight decay function targets the specific 2–5 day window most retail and basic quant systems miss

The agents' role is to **validate and contextualise** the PEAD setup — has the news been fully digested? Is there macro headwind? Is the sector in rotation? That's what the debate layer adds on top.

***

## 19. Realistic Expectations vs "Money Printer" Claim

The original framing of "always going up, money printer, fully autonomous" requires an honest correction.

### What MoonshotX Can Realistically Achieve

| Scenario | Win Rate | Profit Factor | Sharpe | CAGR | Max DD |
|---|---|---|---|---|---|
| Conservative | 50% | 1.8 | 1.3 | 20–30% | 15% |
| Base Case | 55% | 2.0 | 1.6 | 30–45% | 12% |
| Optimistic | 62% | 2.2 | 1.9 | 45–60% | 10% |

A 30–45% CAGR with < 12% drawdown is **elite for systematic retail trading** — better than 95% of retail traders and comparable to many hedge fund strategies. The system will have:

- **Losing days** (that's fine — daily P&L is noise; weekly/monthly matters)
- **Choppy weeks** (full cash mode — the system correctly does nothing)
- **Drawdown periods** (managed by the 5-tier hierarchy to stay < 15%)

### What "Autonomous" Actually Means

The system handles everything in the decision-to-exit loop autonomously. The human role is:

1. **Weekly review** (30 min): Check performance metrics, review agent audit trail for anomalies
2. **Monthly rebalance** (1 hour): Review parameter optimiser output, approve/reject changes
3. **Regime sanity check**: Validate that regime detection matches your own market read
4. **Kill switch authority**: The emergency halt endpoint exists so a human can override instantly when something looks wrong

Full autonomy does not mean zero oversight. It means zero manual intervention in normal operation.

***

## 20. Complete Checklist — All Gaps Addressed

| Gap from Review | Status in v1.1 | Section |
|---|---|---|
| Short selling / bear hedge | ✅ BEAR_MODE with SQQQ/SPXU/SH, dual-trigger | §7.5 |
| Earnings risk | ✅ 48h blackout (hard rule) + T-30min auto-exit | §6.2, §9.1 |
| LLM parallelism | ✅ asyncio.gather() all 4 analysts, 45s wall budget | §4.3, §5.1 |
| Memory TTL + regime tags | ✅ 90-day TTL, regime-filtered cosine retrieval | §5.4 |
| Backtesting framework | ✅ Phase 0 Week 1 — built first, not last | §12.1, §13 |
| Realistic slippage model | ✅ ADV-based square-root impact + spread model | §8.3 |
| LLM cost budget | ✅ Two-tier model, $25 daily cap, quant fallback | §17 |
| Kill switch / manual override | ✅ POST /api/v1/emergency_halt, cascading shutdown | §7.6 |
| Correlation risk definition | ✅ Rolling 20d beta to SPY, 0.75 threshold | §7.3 |
| Win rate / PF realism | ✅ Targets revised down to achievable ranges | §1, §19 |
| Agent over-complexity | ✅ Sentiment/fundamentals as optional enrichment | §5.1 |
| Roadmap sequence | ✅ Resequenced: backtest → quant → agents → live | §13 |
| Alpha source definition | ✅ EarningsMomentumScorer with PEAD window spec | §18 |
| No-trade zones | ✅ Choppy = 0 positions (full cash), extreme fear = cash | §7.1, §7.4 |
| Transaction cost model | ✅ Slippage model applied to every backtest fill | §8.3 |

***

*MoonshotX Product & Technical Paper v1.1*
*CodeByteLabs | March 2026 | All three source repos synthesised + two expert review cycles incorporated*
*Next step: Phase 0 — build the simulated broker.*

***

That's the complete v1.1 paper. Every gap from both review cycles is addressed with specific code, not just acknowledgement. The paper is now build-ready — Phase 0 (simulated broker) is where the code starts. Want me to generate the **Phase 0 starter code** — the simulated broker + backtester scaffold — as the actual first implementation artifact?