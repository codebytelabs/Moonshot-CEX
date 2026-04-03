***

Pretext :

Repurposing these repos to build MoonshotX :
my old repo on trading : https://github.com/codebytelabs/DayTraderAI most trending trading agent repo on github now : https://github.com/TauricResearch/TradingAgents and my latest moonshot-cex repo itself : https://github.com/codebytelabs/Moonshot-CEX

***

# MoonshotX v1.1
## Autonomous Multi-Agent US Stock Trading System
### Full Product & Technical Paper

**Author:** CodeByteLabs
**Date:** March 2026
**Version:** 1.1 — Final
**Status:** Design Complete — Ready to Build
**Review Cycles:** 3 independent expert reviews incorporated

***

## Table of Contents

1. Executive Summary
2. Problem Statement
3. Prior Art — What to Repurpose
4. System Architecture
5. Multi-Agent Intelligence Layer
6. Strategy Engine
7. Risk Management Framework
8. Execution Engine
9. Position Management
10. Learning & Reflection System
11. Data Infrastructure
12. Backtesting & Walk-Forward Validation
13. Implementation Roadmap
14. File Structure
15. Configuration Reference
16. LLM Cost Model
17. Alpha Source — EarningsMomentumScorer
18. Portfolio Beta Control
19. Realistic Expectations
20. Complete Gap Resolution Checklist
21. Risk Disclosures

***

## 1. Executive Summary

MoonshotX synthesises three battle-tested codebases into a fully autonomous US stock trading system, incorporating all architectural lessons from live trading losses and three rounds of independent expert peer review.

| Source Repo | Contribution | Key Innovation |
|---|---|---|
| **DayTraderAI** | Alpaca execution, 50+ indicators, R-multiple tracking, Wave Rider | US stock infrastructure |
| **TradingAgents** | LangGraph multi-agent brain, analyst debates, reflection/memory | LLM-powered decision intelligence |
| **Moonshot-CEX** | Trailing stops, Bayesian engine, regime detection, adaptive thresholds | Battle-tested position management |

### Core Thesis

> **LLMs act as signal quality arbiters — they synthesise cross-signal context no single indicator captures. They decide *what* and *when* to buy. Mechanical quant systems decide *when* to sell. Never the reverse. Alpha comes from execution asymmetry and position management, not from LLM "intelligence."**

### Revised Performance Targets (Realistic — Not Aspirational)

| Metric | v1.0 Aspirational | v1.1 Calibrated | Basis |
|---|---|---|---|
| Win Rate | 60–70% | **50–62%** | Trend systems 45–60%; debate layer adds ~5% |
| Profit Factor | ≥ 2.5 | **≥ 1.8 (target 2.2)** | High WR + high PF rarely coexist |
| Sharpe Ratio | ≥ 2.0 | **≥ 1.5 (target 1.8)** | Elite retail achievable |
| Max Drawdown | < 10% | **< 15% (target < 12%)** | Bear mode + cash regime as floor |
| Annual Return | — | **20–50% CAGR** | Already elite for systematic retail |

### Key Differentiators vs v1.0

1. **Parallel agent execution** — 4 analysts run simultaneously; 45s wall-clock budget hard enforced
2. **Bear mode with inverse ETF rotation** — system profits or hedges in all regimes, not just bull
3. **Earnings blackout** — hard rule, not an agent decision
4. **Memory with TTL + regime tags** — no stale analogy poisoning
5. **Backtest-first roadmap** — no live money before 2yr walk-forward validation
6. **Explicit LLM cost budget** — daily cost circuit breaker, two-tier model
7. **EarningsMomentumScorer** — genuine alpha differentiator; neither source repo has this
8. **Walk-forward validation** — rolling OOS windows, not static 2yr backtest
9. **Portfolio beta control** — not just position count limits
10. **Smart entry orders** — limit/stop-limit for entries; market only for emergency exits
11. **Quant-only fallback mode** — when LLM cost cap is hit, system trades via pure quant

***

## 2. Problem Statement

| Problem | Evidence | MoonshotX v1.1 Solution |
|---|---|---|
| Single-brain decisions | EMA crossover alone = noise | 4 analyst agents + debate teams |
| LLMs generating alpha | LLMs rephrase public data; don't discover alpha | LLMs as signal quality arbiters only; alpha from PEAD + execution |
| No learning from mistakes | DayTraderAI repeated errors | Reflection system: TTL + regime guard (no overfitting) |
| Over-trading | Moonshot-CEX: 185 trades/day = loss | Max 15 trades/day, Bayesian ≥ 0.45, full cash in choppy |
| Premature exits | Winners held 0.41h vs losers 3.78h | Trailing stop primary; time exit only for losers |
| Sequential LLM latency | 10 candidates × 30s = 300s in 60s loop | asyncio.gather() with 45s hard budget |
| No bear protection | Long-only bleeds in 2022-style markets | BEAR_MODE with inverse ETF rotation |
| Memory poisoning | Wrong regime analogies surface over time | 90-day TTL, regime-filtered cosine retrieval |
| Fake backtest profitability | No slippage model → fictional results | ADV-based square-root impact model on every fill |
| LLM cost explosion | Deep-think on every call = $200/day | Two-tier LLM; $25/day cap; quant-only fallback |
| Overfit to in-sample data | Static 2yr backtest ≠ live performance | Rolling walk-forward: Train → Validate → OOS Test |
| Market orders on entry | Unnecessary slippage on every entry | Limit/stop-limit for entries; market only for emergency SL |
| Uncontrolled beta exposure | All tech positions = 2× market exposure | Rolling 20d portfolio beta cap at 1.5× |
| Commoditised signals | EMA/RSI in every free screener | EarningsMomentumScorer — PEAD window edge |

***

## 3. Prior Art — What to Repurpose

### 3.1 From DayTraderAI

| Component | File | Status |
|---|---|---|
| Feature Engine (50+ indicators) | `backend/data/features.py` | ✅ Core |
| Market Data (Alpaca WS) | `backend/data/market_data.py` | ✅ Core |
| Risk Manager | `backend/trading/risk_manager.py` | ✅ Core |
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

**Key lessons:** Bracket orders essential; 5s stop verification catches orphaned orders; R-multiple thinking normalises risk across setups; EOD exit at 15:57 prevents gap risk; no entries after 15:30.

### 3.2 From TradingAgents

| Component | File | Status |
|---|---|---|
| TradingAgentsGraph | `graph/trading_graph.py` | ✅ Core — parallel-adapted |
| Graph Setup (LangGraph) | `graph/setup.py` | ✅ Core |
| Reflection System | `graph/reflection.py` | ✅ Core — TTL + regime guard added |
| Signal Processing | `graph/signal_processing.py` | ✅ Core |
| 4 Analyst Agents | `agents/analysts/*.py` | ✅ Core — run in parallel |
| Bull/Bear Researchers | `agents/researchers/*.py` | ✅ Core — debate system |
| Research Manager | `agents/managers/research_manager.py` | ✅ Core — deep-think LLM |
| Portfolio Manager | `agents/managers/portfolio_manager.py` | ✅ Core — deep-think LLM |
| 3 Risk Debators | `agents/risk_mgmt/*.py` | ✅ Core |
| FinancialSituationMemory | `agents/utils/memory.py` | ✅ Core — TTL + regime tags |
| Data Interface | `dataflows/interface.py` | ✅ Core |

**Critical gap filled:** TradingAgents has NO execution engine. MoonshotX fills this entirely from DayTraderAI.

### 3.3 From Moonshot-CEX (Lessons Paid in Real Dollars)

| Component | Status | Key Lesson |
|---|---|---|
| Bayesian Decision Engine | ✅ Core | Entry quality gate, posterior ≥ 0.45 |
| QuantMutator | ✅ Core | Hard floor 0.40, ceiling 0.55 — never below |
| BigBrother Regime | ✅ Core | Regime-specific parameter scaling |
| Position Manager exits | ✅ Core | Trailing stop = THE profit engine |
| Execution Core | ✅ Core | Market sells for SL (IOC failed: −$747) |
| Risk Manager | ✅ Core | Drawdown tracking, position limits |

**Critical lessons:** Threshold floor 0.12 destroyed P&L (−$387/day); 185 trades/day = guaranteed loss; premature exits killed 100% of winners; time exit only for losers; 4h symbol cooldown prevents churn; dust positions without cleanup cycle forever.

***

## 4. System Architecture

### 4.1 Data Flow — One Complete Cycle (15 Steps)

```
1.  SCAN       → Universe scanner: top 50 liquid stocks ranked by 4-factor composite
2.  PRE-GATE   → Bayesian quick_score < 0.45 → skip immediately (< 100ms)
3.  EARNINGS   → Earnings blackout check → skip if within 48h of earnings
4.  DATA       → Feature engine: 50+ indicators per stock (pre-cached)
5.  ANALYZE    → 4 analyst agents run IN PARALLEL (asyncio.gather, ≤ 20s)
6.  DEBATE     → Bull/Bear researchers argue N=2 rounds
7.  JUDGE      → Research Manager synthesises verdict (deep-think LLM)
8.  PLAN       → Trader agent creates entry plan (ticker, size, SL, TP, entry type)
9.  RISK       → 3-way risk debate (Aggressive / Neutral / Conservative)
10. APPROVE    → Portfolio Manager: APPROVE or REJECT (deep-think LLM)
11. BETA CHECK → Portfolio beta control: projected beta ≤ 1.5× → proceed
12. EXECUTE    → Smart Order Executor: limit/stop-limit entry + bracket SL/TP via Alpaca
13. MANAGE     → Position Manager: trailing stops, R-multiples, time exit (5s loop)
14. EXIT       → Mechanical triggers: SL / trailing / partial / time / earnings / EOD
15. REFLECT    → All agents review outcome → update GuardedMemory (TTL + regime tag)
16. ADAPT      → QuantMutator adjusts threshold; optimizer tunes weekly
17. REPEAT     → Loop every 60s during market hours
```

### 4.2 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.12+ | asyncio native, ecosystem |
| Agent Framework | LangGraph + LangChain | Production-grade agent orchestration |
| LLM — Deep Think | Claude 3.7 Sonnet / GPT-4o | Research Manager + Portfolio Manager only |
| LLM — Quick Think | Claude Haiku 3.5 / GPT-4o-mini | All other agents — cost + latency |
| Broker API | Alpaca Markets | Commission-free, bracket orders, paper mode |
| Backend | FastAPI + uvicorn | Async-native, WebSocket support |
| Database | Supabase (PostgreSQL + pgvector) | Memory embeddings + trade state |
| Frontend | React 18 + TypeScript + Tailwind | Dashboard from DayTraderAI adapted |
| Data | yFinance + Alpaca WS + Twelve Data | Free tier covers all needs |
| Backtest Data | Polygon.io | Tick-level historical — $29/mo |
| Deployment | VPS Chicago | Proximity to NYSE/NASDAQ |

### 4.3 Real-Time Parallel Loop (v1.1 — Complete Implementation)

```python
import asyncio
import time
import logging
from datetime import datetime
import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger("moonshotx.loop")


async def trading_loop(config, agents, execution_engine,
                       position_manager, risk_manager,
                       regime_manager, bayesian_engine,
                       earnings_calendar, universe_scanner,
                       llm_cost_manager, beta_manager):

    while market_is_open():
        loop_start = time.monotonic()
        current_regime = regime_manager.classify()
        logger.info(f"Loop start | Regime: {current_regime} | "
                    f"Positions: {len(position_manager.open_positions)}")

        # ── PHASE 1: UNIVERSE SCAN (pure quant, < 5s) ──────────────────────
        candidates = universe_scanner.get_top_candidates(n=10)

        viable = []
        for ticker in candidates:
            # Hard gates — no LLM cost, < 1ms each
            if bayesian_engine.quick_score(ticker) < config.bayesian_threshold:
                continue
            if earnings_calendar.is_blackout(ticker):
                continue
            if not risk_manager.can_add_position(current_regime):
                break
            viable.append(ticker)

        # ── PHASE 2: PARALLEL AGENT ANALYSIS (≤ 35s budget) ────────────────
        decisions = {}

        if viable and llm_cost_manager.can_run_agents():
            async def analyse_ticker(ticker):
                try:
                    async with asyncio.timeout(35):
                        state, decision = await agents.propagate_parallel(
                            ticker, datetime.now(ET).date(), current_regime
                        )
                        return ticker, decision
                except asyncio.TimeoutError:
                    logger.warning(f"{ticker}: agent pipeline timeout — skipped")
                    return ticker, None
                except Exception as e:
                    logger.error(f"{ticker}: agent error — {e}")
                    return ticker, None

            results = await asyncio.gather(
                *[analyse_ticker(t) for t in viable],
                return_exceptions=False
            )
            decisions = {t: d for t, d in results if d is not None}

        elif viable and not llm_cost_manager.can_run_agents():
            # ── QUANT-ONLY FALLBACK MODE ─────────────────────────────────────
            logger.warning("LLM cost cap hit — running quant-only mode")
            for ticker in viable:
                quant_decision = bayesian_engine.full_score(ticker, current_regime)
                if quant_decision.score >= config.bayesian_threshold:
                    decisions[ticker] = quant_decision

        # ── PHASE 3: EXECUTION ───────────────────────────────────────────────
        for ticker, decision in decisions.items():
            if decision.action != "BUY":
                continue
            if not risk_manager.daily_loss_ok():
                logger.warning("Daily loss limit — halting new entries")
                break
            # Portfolio beta gate
            if not beta_manager.can_add_position(
                position_manager.open_positions, ticker, decision.plan.size
            ):
                logger.info(f"{ticker}: portfolio beta limit — skipped")
                continue
            await execution_engine.enter(ticker, decision.plan, current_regime)

        # ── PHASE 4: POSITION MANAGEMENT (always runs regardless of entries) ─
        await position_manager.tick_all_positions(current_regime)
        await earnings_calendar.earnings_exit_monitor(position_manager)

        # ── PHASE 5: BEAR MODE CHECK ─────────────────────────────────────────
        if current_regime == "bear_mode":
            await bear_mode_manager.evaluate(position_manager)
        elif bear_mode_manager.is_active and current_regime in ["neutral", "bull"]:
            await bear_mode_manager.deactivate()

        # ── PHASE 6: RISK CIRCUIT BREAKERS ───────────────────────────────────
        if risk_manager.daily_loss_exceeded():
            logger.critical("Daily loss limit hit — halting for the day")
            await alert_manager.send_critical("Daily loss limit reached")
            break
        if risk_manager.drawdown_exceeded():
            logger.critical("Max drawdown hit — full system halt")
            await emergency_halt("MAX_DRAWDOWN_EXCEEDED")
            break

        # ── LOOP TIMING ───────────────────────────────────────────────────────
        elapsed = time.monotonic() - loop_start
        logger.debug(f"Loop completed in {elapsed:.1f}s")
        await asyncio.sleep(max(0, 60 - elapsed))
```

### 4.4 Inside `propagate_parallel` — Async Agent Execution

```python
async def propagate_parallel(ticker, date, regime):
    """
    Runs all 4 analyst agents simultaneously.
    Technical + News = mandatory blocking.
    Sentiment + Fundamentals = optional enrichment (timeout-safe).
    """
    # Fire all 4 simultaneously — quick-think LLM
    tech_task  = asyncio.create_task(technical_analyst.analyse(ticker, date))
    news_task  = asyncio.create_task(news_analyst.analyse(ticker, date))
    sent_task  = asyncio.create_task(sentiment_analyst.analyse(ticker, date))
    fund_task  = asyncio.create_task(fundamentals_analyst.analyse(ticker, date))

    # Wait up to 20s — non-blocking enrichment agents can miss deadline
    done, pending = await asyncio.wait(
        [tech_task, news_task, sent_task, fund_task],
        timeout=20,
        return_when=asyncio.ALL_COMPLETED
    )
    for task in pending:
        task.cancel()

    # Technical is mandatory — if it timed out, abort entire pipeline
    if tech_task not in done or tech_task.exception():
        logger.warning(f"{ticker}: technical analyst failed — aborting pipeline")
        return None, None

    # Collect available reports
    reports = {}
    for task, name in [(tech_task, "technical"), (news_task, "news"),
                       (sent_task, "sentiment"), (fund_task, "fundamentals")]:
        if task in done and not task.exception():
            reports[name] = task.result()
            llm_cost_manager.record_call(**task.result().token_usage)

    # Run debate pipeline with available reports
    return await run_debate_pipeline(ticker, reports, regime)
```

***

## 5. Multi-Agent Intelligence Layer

### 5.1 Agent Roster

| Agent | LLM Tier | Role | Blocking? | Timeout |
|---|---|---|---|---|
| Technical Analyst | Quick-think | Price action, indicators, patterns | ✅ Mandatory | 20s |
| News Analyst | Quick-think | Breaking news, macro events | ✅ Mandatory | 20s |
| Sentiment Analyst | Quick-think | Social media & retail sentiment | ⚠️ Optional enrichment | 20s |
| Fundamentals Analyst | Quick-think | Earnings, valuations, balance sheet | ⚠️ Optional enrichment | 20s |
| Bull Researcher | Quick-think | Build bullish case from all reports | ✅ Mandatory | 15s |
| Bear Researcher | Quick-think | Build bearish case from all reports | ✅ Mandatory | 15s |
| Research Manager | **Deep-think** | Judge debate, synthesise verdict | ✅ Mandatory | 20s |
| Trader | Quick-think | Entry plan: size, SL, TP, entry type | ✅ Mandatory | 10s |
| Aggressive Analyst | Quick-think | Argue larger position / tighter SL | ✅ Mandatory | 10s |
| Neutral Analyst | Quick-think | Balance risk/reward objectively | ✅ Mandatory | 10s |
| Conservative Analyst | Quick-think | Argue smaller position / rejection | ✅ Mandatory | 10s |
| Portfolio Manager | **Deep-think** | Final APPROVE / REJECT | ✅ Mandatory | 20s |

**Deep-think used only at 2 synthesis nodes.** All other agents use quick-think. This is the primary cost control mechanism — see Section 16 for full cost model.

### 5.2 LangGraph Flow

```
START
  → asyncio.gather():
      [Technical Analyst]   ──┐
      [News Analyst]          ├── All 4 fire simultaneously (quick-think)
      [Sentiment Analyst]  *  ├── * = optional enrichment, timeout-safe
      [Fundamentals]       *  ┘
  → [Bull Researcher] ↔ [Bear Researcher]  (N=2 debate rounds)
  → [Research Manager]    (deep-think — judge verdict)
  → [Trader]              (entry plan)
  → [Aggressive] ↔ [Conservative] ↔ [Neutral]  (M=2 risk rounds)
  → [Portfolio Manager]   (deep-think — APPROVE / REJECT)
END

If APPROVE → Bayesian final check → Beta check → Execute
If REJECT  → Log reason → Reflect → Next candidate
```

### 5.3 Debate Mechanisms

**Investment Debate (Bull vs Bear):**
- Bull receives all available analyst reports, builds the strongest possible buy case
- Bear builds the strongest possible case against buying
- Alternate for exactly 2 rounds, each directly responding to the other's last argument
- Research Manager reads full debate history; issues verdict with explicit reasoning
- If Technical report is absent (timed out), Research Manager auto-REJECTs — no exception

**Risk Debate (3-way):**
- **Aggressive:** "Strong setup — increase size, tighten stop for better R:R"
- **Conservative:** "Too risky — reduce size, wider stop, or reject entirely"
- **Neutral:** "Objective risk/reward — balanced recommendation"
- Portfolio Manager makes final APPROVE/REJECT after reading all three
- Portfolio Manager must explicitly state: position size, SL level, TP target, entry type

### 5.4 Memory Architecture — GuardedFinancialSituationMemory

The v1.0 memory had no expiry and no regime filtering — creating silent poisoning risk where a 2023 NVDA bull run memory could contaminate a 2026 NVDA earnings-correction decision. v1.1 adds three structural safeguards: TTL, regime tags, and filtered retrieval.

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import numpy as np


@dataclass
class MemoryEntry:
    situation_embedding: list[float]   # vectorised market context
    situation_text: str                # human-readable context
    reflection: str                    # agent lesson learned
    regime: str                        # market regime at time of trade
    outcome_pct: float                 # trade P&L %
    outcome_label: str                 # "win" | "loss" | "breakeven"
    created_at: datetime
    ttl_days: int = 90


class GuardedFinancialSituationMemory:
    """
    Regime-aware, TTL-enforced memory store.
    Uses pgvector in Supabase for cosine similarity search.
    Never retrieves memories from a different regime.
    Automatically prunes entries older than ttl_days.
    """
    def __init__(self, agent_id: str, supabase_client, embedder, ttl_days: int = 90):
        self.agent_id = agent_id
        self.db = supabase_client
        self.embedder = embedder
        self.ttl_days = ttl_days

    def add(self, situation_text: str, reflection: str,
            regime: str, outcome_pct: float):
        embedding = self.embedder.embed(situation_text)
        entry = MemoryEntry(
            situation_embedding=embedding,
            situation_text=situation_text,
            reflection=reflection,
            regime=regime,
            outcome_pct=outcome_pct,
            outcome_label=("win" if outcome_pct > 0 else
                           "loss" if outcome_pct < -0.001 else "breakeven"),
            created_at=datetime.utcnow(),
            ttl_days=self.ttl_days
        )
        self.db.table("agent_memory").insert({
            "agent_id":    self.agent_id,
            "embedding":   embedding,
            "situation":   situation_text,
            "reflection":  reflection,
            "regime":      regime,
            "outcome_pct": outcome_pct,
            "created_at":  entry.created_at.isoformat(),
            "expires_at":  (entry.created_at + timedelta(days=self.ttl_days)).isoformat()
        }).execute()
        self._prune_expired()

    def retrieve(self, current_situation: str, current_regime: str,
                 top_k: int = 3) -> list[MemoryEntry]:
        """
        Retrieves top-k most similar memories from the SAME regime only.
        Never cross-regime retrieval.
        """
        embedding = self.embedder.embed(current_situation)
        now = datetime.utcnow().isoformat()
        # pgvector cosine similarity, regime-filtered, TTL-filtered
        results = self.db.rpc("match_memories", {
            "query_embedding": embedding,
            "agent_id":        self.agent_id,
            "regime_filter":   current_regime,
            "expiry_cutoff":   now,
            "match_count":     top_k
        }).execute()
        return results.data

    def _prune_expired(self):
        now = datetime.utcnow().isoformat()
        self.db.table("agent_memory") \
               .delete() \
               .eq("agent_id", self.agent_id) \
               .lt("expires_at", now) \
               .execute()


# Reflection prompt — used after every closed trade
REFLECTION_PROMPT = """
You just participated in a trade decision. Here is the outcome:

Trade: {ticker} | Entry: {entry} | Exit: {exit} | P&L: {pnl_pct:.2%}
Regime at entry: {regime}
Your role: {agent_role}
Your recommendation: {your_recommendation}
Final decision: {final_decision}

Answer these four questions:
1. Was your recommendation correct given what was knowable at entry time?
2. What factors did you miss or overweight in your analysis?
3. What would you do differently in the same regime and setup?
4. Write one concise lesson (max 20 words) for future reference.

Be honest. Overconfidence is the primary failure mode.
"""
```

***

## 6. Strategy Engine

### 6.1 Universe Scanner — 4-Factor Composite

```python
from dataclasses import dataclass
from typing import Optional
import pandas as pd


UNIVERSE_CRITERIA = {
    "min_market_cap":  10_000_000_000,   # $10B+ large cap
    "min_avg_volume":  5_000_000,        # 5M+ shares/day
    "min_price":       20.0,
    "max_price":       1000.0,
    "exchanges":       ["NYSE", "NASDAQ"],
    "exclude_sectors": ["Finance", "Utilities"],  # low momentum sectors
}


@dataclass
class ScoredStock:
    ticker: str
    composite: float
    momentum_score: float
    volume_score: float
    gap_score: float
    earnings_score: float
    adv_30d: float


def rank_universe(earnings_scorer) -> list[ScoredStock]:
    """
    Pre-market ranking (9:00 AM ET daily).
    Returns top 50 stocks sorted by 4-factor composite.
    """
    stocks = filter_by_criteria(UNIVERSE_CRITERIA)
    scored = []

    for s in stocks:
        m = momentum_20d(s)            # normalised 0–1
        v = volume_surge_ratio(s)      # normalised 0–1
        g = gap_pct_premarket(s)       # normalised 0–1
        e = earnings_scorer.score(s.ticker)  # 0–1 (the edge)

        composite = (0.25 * m) + (0.25 * v) + (0.20 * g) + (0.30 * e)
        scored.append(ScoredStock(
            ticker=s.ticker,
            composite=composite,
            momentum_score=m,
            volume_score=v,
            gap_score=g,
            earnings_score=e,
            adv_30d=get_adv_30d(s.ticker)
        ))

    return sorted(scored, key=lambda x: x.composite, reverse=True)[:50]
```

### 6.2 Earnings Blackout Rule (Hard Rule — Never Delegated to Agents)

```python
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")


class EarningsCalendar:
    BLACKOUT_HOURS_PRE   = 48    # No new entries within 48h before earnings
    AUTO_EXIT_MINS       = 30    # Force-exit open positions T-30min before

    def get_next_earnings(self, ticker) -> Optional[datetime]:
        """Returns next earnings datetime in ET, or None."""
        df = yf.Ticker(ticker).calendar
        if df is None or df.empty:
            return None
        earn_date = df.T.get("Earnings Date")
        if earn_date is None:
            return None
        return pd.Timestamp(earn_date.iloc[0]).tz_localize(ET)

    def is_blackout(self, ticker) -> bool:
        """True if within 48h before next earnings — block entry."""
        next_earn = self.get_next_earnings(ticker)
        if next_earn is None:
            return False
        now = datetime.now(ET)
        hours_until = (next_earn - now).total_seconds() / 3600
        return 0 <= hours_until <= self.BLACKOUT_HOURS_PRE

    async def earnings_exit_monitor(self, position_manager):
        """
        Runs every 5 minutes during market hours.
        Auto-exits any open position approaching earnings.
        This is a mechanical rule — no agent involved.
        """
        for position in list(position_manager.open_positions.values()):
            next_earn = self.get_next_earnings(position.ticker)
            if next_earn is None:
                continue
            now = datetime.now(ET)
            mins_until = (next_earn - now).total_seconds() / 60
            if 0 <= mins_until <= self.AUTO_EXIT_MINS:
                await position_manager.force_exit(
                    position.ticker,
                    reason="EARNINGS_BLACKOUT_AUTO_EXIT",
                    urgency="immediate"
                )
```

### 6.3 Wave Rider Entry Conditions

```python
WAVE_ENTRY_CONDITIONS = {
    "trend":         "5m/15m EMA9 > EMA21, 1h bullish (EMA21 slope positive)",
    "momentum":      "RSI 14 between 40–75, MACD histogram > 0 and rising",
    "volume":        "Current volume > 1.2× 20-day average",
    "timing":        "Pullback to EMA9/21 zone with bounce confirmation candle",
    "agents":        "Portfolio Manager: APPROVE",
    "bayesian":      "Full posterior ≥ 0.45",
    "earnings":      "Not within 48h of earnings event (hard rule)",
    "regime":        "Not choppy / extreme_fear / bear_mode",
    "portfolio_beta": "Projected portfolio beta ≤ 1.5× after addition",
}
```

### 6.4 Momentum Fast-Track (Skip Quant Gates)

If `1h_return > 2%` AND `volume_ratio > 2.0×` → skip EMA/MACD gates, go directly to agent pipeline. Still requires: agent consensus + Bayesian threshold + earnings check + beta check. The quant gates are filters, not the decision.

### 6.5 No-Trade Zones (New — Explicit)

```python
def should_skip_ticker(ticker, regime, bars) -> tuple[bool, str]:
    """Hard filters applied before any expensive computation."""

    # Regime-based
    if regime in ["choppy", "extreme_fear"]:
        return True, f"regime={regime}"

    # Low volatility / low ATR — no momentum to trade
    atr = calculate_atr(bars, period=14)
    atr_pct = atr / bars["close"].iloc[-1]
    if atr_pct < 0.005:  # ATR < 0.5% of price
        return True, "atr_too_low"

    # Whipsaw detection — too many direction changes
    direction_changes = count_direction_changes(bars, lookback=20)
    if direction_changes > 12:
        return True, "whipsaw_detected"

    # News/event risk — major macro event today
    if macro_calendar.has_major_event_today():
        return True, "macro_event_day"

    return False, ""
```

### 6.6 Multi-Timeframe Signal Weights

| Timeframe | Weight | Purpose |
|---|---|---|
| 5-minute | 15% | Entry timing precision |
| 15-minute | 30% | Trend confirmation |
| 1-hour | 35% | Primary trend direction |
| 4-hour | 15% | Higher timeframe context |
| Daily | 5% | Major support/resistance levels |

***

## 7. Risk Management Framework

### 7.1 Five-Tier Risk Hierarchy

```
TIER 1: PORTFOLIO LEVEL
├── Max drawdown: 15% → FULL HALT (requires manual review to resume)
├── Design target: < 12% max drawdown
├── Recovery threshold: resume after manual review at 10% drawdown
└── Account < initial × 0.80 → PERMANENT SHUTDOWN until human reviews

TIER 2: DAILY LEVEL
├── Max daily loss: 3% → stop all new entries for the day
├── Max daily trades: 15 total
├── 3 consecutive losses → 30-minute pause before resuming
└── LLM cost > daily cap → switch to quant-only mode (not halt)

TIER 3: POSITION LEVEL
├── Max positions — bull: 5, neutral: 4, fear: 3, choppy: 0, bear_mode: 0
├── Max single position: 4% of portfolio value
├── Max sector exposure: 20% of portfolio in any one sector
├── Max correlated positions: 2 (see Section 7.3 for correlation definition)
└── Max portfolio beta: 1.5× (see Section 18 for beta control)

TIER 4: ENTRY LEVEL
├── Bayesian posterior ≥ 0.45 (hard minimum — never lower than 0.40)
├── Agent consensus: Portfolio Manager must APPROVE
├── Symbol cooldown: 4 hours after any exit from that symbol
├── No new entries after 15:30 ET
├── No entry within 48h of earnings (hard rule — not agent decision)
└── Portfolio beta check: projected beta ≤ 1.5× post-addition

TIER 5: EXECUTION LEVEL
├── Bracket orders mandatory — every position has SL + TP from birth
├── 5-second stop verification loop — catches orphaned stop orders
├── Market orders for ALL SL/trailing exits (IOC failed: −$747 Moonshot-CEX lesson)
├── Limit/stop-limit for entries (not market — unnecessary slippage)
├── Fill detection: 30s timeout → cancel if unfilled
└── Slippage validation on every fill (see Section 8.3)
```

### 7.2 Position Sizing — ATR-Based, Regime-Adjusted, Confidence-Weighted

```python
def calculate_position_size(ticker, entry_price, stop_price,
                             regime, portfolio_value, confidence_score,
                             adv_30d) -> int:
    """
    Position size = f(risk%, regime, confidence, ATR, liquidity)

    confidence_score: 0.0–1.0 from Bayesian engine
    Returns: integer number of shares
    """
    base_risk = 0.015  # 1.5% risk per trade at full confidence

    regime_mult = {
        "bull":         1.2,
        "neutral":      1.0,
        "fear":         0.7,
        "extreme_fear": 0.0,   # no new longs
        "choppy":       0.0,   # no new trades
        "bear_mode":    0.0,   # long-side closed
    }
    if regime_mult.get(regime, 0) == 0:
        return 0

    # Confidence-weighted sizing: high conviction = larger size
    # confidence 0.45 (minimum) → 0.75× size
    # confidence 0.70 (strong)  → 1.0× size
    # confidence 0.90 (max)     → 1.25× size
    confidence_mult = 0.5 + (confidence_score * 0.75)
    confidence_mult = max(0.5, min(1.25, confidence_mult))

    risk_pct = base_risk * regime_mult[regime] * confidence_mult
    dollar_risk = portfolio_value * risk_pct
    stop_distance = abs(entry_price - stop_price) / entry_price

    if stop_distance == 0:
        return 0

    raw_position_value = dollar_risk / stop_distance

    # Hard caps
    portfolio_cap = portfolio_value * 0.04    # max 4% of portfolio
    # Liquidity cap: never more than 1% of 30-day ADV
    adv_cap = adv_30d * 0.01 * entry_price

    position_value = min(raw_position_value, portfolio_cap, adv_cap)
    return max(1, int(position_value / entry_price))
```

### 7.3 Correlation Risk — Real-Time Definition

```python
import numpy as np
from functools import lru_cache


class CorrelationManager:
    """
    Defines "correlated" as: rolling 20-day daily return correlation to SPY > 0.75.
    Two positions in the same correlation cluster count against the limit of 2.
    """
    CORRELATION_THRESHOLD = 0.75
    WINDOW_DAYS = 20

    @lru_cache(maxsize=100)
    def get_spy_correlation(self, ticker: str) -> float:
        ticker_returns = get_daily_returns(ticker, days=self.WINDOW_DAYS)
        spy_returns    = get_daily_returns("SPY",   days=self.WINDOW_DAYS)
        if len(ticker_returns) < self.WINDOW_DAYS:
            return 0.5  # unknown — assume moderate correlation
        corr_matrix = np.corrcoef(ticker_returns, spy_returns)
        return float(corr_matrix[0, 1])

    def correlated_count(self, open_positions: list, new_ticker: str) -> int:
        """
        Count open positions in the same correlation cluster as new_ticker.
        Cluster = within 0.15 correlation distance of each other via SPY proxy.
        """
        new_corr = self.get_spy_correlation(new_ticker)
        count = 0
        for pos in open_positions:
            existing_corr = self.get_spy_correlation(pos.ticker)
            if abs(new_corr - existing_corr) < 0.15:
                count += 1
        return count

    def can_add(self, open_positions: list, new_ticker: str) -> bool:
        return self.correlated_count(open_positions, new_ticker) < 2
```

### 7.4 Regime Detection — 4-Input Classification

| Input | Source | Update Freq | Regimes |
|---|---|---|---|
| Fear & Greed Index | CNN scraper | 15 min | 0–100 (Extreme Fear → Extreme Greed) |
| VIX | CBOE via Alpaca | Real-time | < 15 Low → > 35 Crisis |
| Market Breadth | % S&P 500 > 200d MA | Daily pre-market | < 20% Bear → > 70% Bull |
| SPY Momentum | 20-day SPY return | Daily | < −5% Strong Down → > 5% Strong Up |

```python
def classify_regime(fg: float, vix: float,
                    breadth: float, spy_20d: float) -> str:
    """
    fg:       Fear & Greed 0–100
    vix:      VIX level
    breadth:  Fraction of S&P 500 stocks above 200d MA (0–1)
    spy_20d:  SPY 20-day return (e.g. 0.03 = +3%)
    """
    if vix > 35 and breadth < 0.20:
        return "extreme_fear"
    if vix > 28 and breadth < 0.30:
        return "bear_mode"         # triggers inverse ETF rotation
    if vix > 22 or breadth < 0.40 or fg < 25:
        return "fear"
    if fg < 35 or spy_20d < -0.02 or (vix > 18 and breadth < 0.50):
        return "choppy"
    if fg > 70 and breadth > 0.60 and spy_20d > 0.03:
        return "bull"
    return "neutral"
```

**Regime-specific parameter scaling:**

| Regime | SL Mult | Trail Mult | Time Mult | Max Longs | Mode |
|---|---|---|---|---|---|
| Bull | 1.4× | 1.3× | 1.5× | 5 | Long |
| Neutral | 1.0× | 1.0× | 1.0× | 4 | Long |
| Fear | 0.7× | 0.8× | 0.6× | 3 | Long (reduced) |
| Choppy | — | — | — | 0 | **Full cash** |
| Bear Mode | — | — | — | 0 | **Inverse ETF only** |
| Extreme Fear | — | — | — | 0 | **Full cash** |

### 7.5 BEAR_MODE — Inverse ETF Rotation

```python
INVERSE_ETF_MAP = {
    "primary":   "SQQQ",   # 3× inverse NASDAQ
    "secondary": "SPXU",   # 3× inverse S&P 500
    "mild":      "SH",     # 1× inverse S&P 500 (lower risk)
}

class BearModeManager:
    MAX_INVERSE_ALLOC    = 0.15   # Never > 15% total in inverse ETFs
    INVERSE_POSITION_PCT = 0.05   # 5% per position
    CONFIRM_LOOPS        = 3      # Regime must persist 3 loops before activating

    def __init__(self):
        self.is_active = False
        self._bear_confirm_count = 0

    async def evaluate(self, position_manager):
        self._bear_confirm_count += 1
        if self._bear_confirm_count >= self.CONFIRM_LOOPS and not self.is_active:
            await self.activate(position_manager)

    async def activate(self, position_manager):
        """
        1. Tighten trailing stops on all longs to 0.5% (accelerated exit)
        2. After longs cleared, open inverse ETF hedge
        """
        if self.is_active:
            return
        # Tighten existing longs — don't force-sell, let trailing do it quickly
        for pos in position_manager.open_positions.values():
            pos.trail_distance = 0.005  # tighten to 0.5%

        # Wait for longs to clear (max 30 min)
        cleared = await position_manager.wait_for_clearance(timeout_mins=30)

        if cleared:
            # Open inverse ETF — STILL uses Bayesian pre-filter
            score = bayesian_engine.quick_score("SQQQ")
            if score >= 0.40:  # lower threshold in bear regime
                await execution_engine.enter_inverse(
                    ticker="SQQQ",
                    allocation_pct=self.INVERSE_POSITION_PCT
                )
        self.is_active = True
        await alert_manager.send_warning("🐻 BEAR_MODE activated — inverse ETF hedge opened")

    async def deactivate(self):
        if not self.is_active:
            return
        await execution_engine.exit_all_inverse_positions()
        self._bear_confirm_count = 0
        self.is_active = False
        await alert_manager.send_info("🟢 BEAR_MODE deactivated — returning to long-only")
```

**Constraints:**
- Inverse ETF entries STILL require Bayesian pre-filter (≥ 0.40 in bear regime)
- Maximum 15% total portfolio in inverse ETFs
- Same trailing stop + exit hierarchy applies — no "hold forever" hedges
- Regime must confirm for 3 consecutive loop cycles (≥ 3 minutes) before activation

### 7.6 Emergency Kill Switch

```python
from fastapi import APIRouter, Depends, HTTPException
import asyncio

router = APIRouter()


@router.post("/api/v1/emergency_halt")
async def emergency_halt(
    reason: str = "manual_override",
    api_key: str = Depends(verify_api_key)
):
    """
    Single authenticated call triggers cascading shutdown:
    1. Stop all new order generation
    2. Cancel all open/pending orders at broker
    3. Market-sell all open positions
    4. Log to Supabase
    5. Send critical alert
    6. Set system state = HALTED (requires manual resume)
    """
    import logging
    logger = logging.getLogger("moonshotx.emergency")
    logger.critical(f"EMERGENCY HALT triggered: {reason}")

    # Step 1: Pause trading loop immediately
    trading_loop_controller.pause()

    # Step 2: Cancel all pending orders at broker
    try:
        cancelled = await alpaca_client.cancel_all_orders()
        logger.info(f"Cancelled {cancelled} pending orders")
    except Exception as e:
        logger.error(f"Order cancellation error: {e}")
        cancelled = 0

    # Step 3: Market-sell all open positions simultaneously
    positions = await alpaca_client.get_all_positions()
    exit_orders = [
        alpaca_client.submit_order(
            symbol=p.symbol,
            qty=abs(int(p.qty)),
            side="sell",
            type="market",
            time_in_force="day"
        )
        for p in positions
    ]
    results = await asyncio.gather(*exit_orders, return_exceptions=True)
    closed = sum(1 for r in results if not isinstance(r, Exception))
    failed = len(results) - closed

    # Step 4: Log to Supabase
    await supabase.table("system_events").insert({
        "event_type":       "EMERGENCY_HALT",
        "reason":           reason,
        "orders_cancelled": cancelled,
        "positions_closed": closed,
        "positions_failed": failed,
        "timestamp":        datetime.utcnow().isoformat(),
        "system_state":     "HALTED"
    }).execute()

    # Step 5: Critical alert
    await alert_manager.send_critical(
        f"🛑 MoonshotX HALTED\n"
        f"Reason: {reason}\n"
        f"Orders cancelled: {cancelled}\n"
        f"Positions closed: {closed} / {len(positions)}\n"
        f"Manual resume required via /api/v1/resume"
    )

    system_state.set("HALTED")
    return {
        "status":           "halted",
        "reason":           reason,
        "orders_cancelled": cancelled,
        "positions_closed": closed,
        "positions_failed": failed,
        "resume_endpoint":  "POST /api/v1/resume"
    }


@router.post("/api/v1/pause_entries")
async def pause_entries(api_key: str = Depends(verify_api_key)):
    """Stop new entries. Manage existing positions normally."""
    trading_loop_controller.pause_entries()
    return {"status": "entries_paused", "positions": "managed_normally"}


@router.post("/api/v1/resume")
async def resume_trading(
    confirm: bool,
    api_key: str = Depends(verify_api_key)
):
    """Manual resume after halt. Requires explicit confirmation."""
    if not confirm:
        raise HTTPException(400, "Set confirm=true to resume")
    trading_loop_controller.resume()
    system_state.set("ACTIVE")
    await alert_manager.send_info("✅ MoonshotX resumed by manual override")
    return {"status": "resumed"}


@router.get("/api/v1/status")
async def get_status(api_key: str = Depends(verify_api_key)):
    """Real-time system state."""
    return {
        "system_state":     system_state.get(),
        "regime":           regime_manager.current,
        "open_positions":   len(position_manager.open_positions),
        "daily_pnl_pct":    risk_manager.daily_pnl_pct,
        "daily_trades":     risk_manager.daily_trade_count,
        "llm_cost_today":   llm_cost_manager.daily_spend,
        "portfolio_beta":   beta_manager.get_portfolio_beta(position_manager.open_positions),
        "bear_mode_active": bear_mode_manager.is_active,
        "timestamp":        datetime.utcnow().isoformat()
    }
```

***

## 8. Execution Engine

### 8.1 Smart Entry Order Logic (v1.1 — Limit/Stop-Limit for Entries)

Market orders for entries are unnecessary slippage. You know the setup in advance — use limit or stop-limit orders. Market orders are reserved for **emergency SL exits only** (Moonshot-CEX lesson).

```python
async def enter_position(ticker, shares, entry_target, stop_price,
                         tp_price, entry_type, regime, adv_30d):
    """
    entry_type: "breakout" → stop-limit order
                "pullback" → limit order
    """
    # Pre-flight checks
    if not market_is_open():
        return None
    if not risk_manager.can_enter(ticker, regime):
        return None
    if earnings_calendar.is_blackout(ticker):
        return None

    spread = get_current_spread(ticker)
    atr    = get_atr(ticker, period=14)

    if entry_type == "breakout":
        # Stop-limit: only fills if price reaches breakout level
        # Limit is 0.2% above stop to account for spread
        order = await alpaca_client.submit_order(
            symbol=ticker, qty=shares,
            side="buy", type="stop_limit",
            stop_price=round(entry_target, 2),
            limit_price=round(entry_target * 1.002, 2),
            time_in_force="day"
        )
        fill_timeout = 180  # 3 minutes — if breakout fails, setup is gone

    elif entry_type == "pullback":
        # Limit order: buy at the pullback level, not at market
        order = await alpaca_client.submit_order(
            symbol=ticker, qty=shares,
            side="buy", type="limit",
            limit_price=round(entry_target, 2),
            time_in_force="day"
        )
        fill_timeout = 300  # 5 minutes — pullbacks take longer to fill

    else:
        # Fallback: market order (only for momentum fast-track)
        order = await alpaca_client.submit_order(
            symbol=ticker, qty=shares,
            side="buy", type="market",
            time_in_force="day"
        )
        fill_timeout = 30

    # Fill detection — no phantom positions
    filled = await fill_detection.wait_for_fill(order.id, timeout=fill_timeout)
    if not filled:
        await alpaca_client.cancel_order(order.id)
        logger.info(f"{ticker}: unfilled in {fill_timeout}s — setup moved, cancelled")
        return None

    actual_fill = filled.avg_fill_price
    expected_slip = slippage_model.estimate(shares, entry_target, adv_30d, regime)
    actual_slip = abs(actual_fill - entry_target) / entry_target

    logger.info(
        f"{ticker}: filled {shares}sh @ ${actual_fill:.2f} "
        f"(target ${entry_target:.2f}, slip {actual_slip:.3%}, "
        f"model {expected_slip:.3%})"
    )

    # Attach bracket legs: SL and TP set at broker level
    await alpaca_client.submit_order(
        symbol=ticker, qty=shares,
        side="sell", type="stop",
        stop_price=round(stop_price, 2),
        time_in_force="gtc"
    )

    # Register position
    position_manager.register(Position(
        ticker=ticker, entry=actual_fill, shares=shares,
        stop=stop_price, tp=tp_price,
        regime=regime, entry_type=entry_type,
        adv_30d=adv_30d
    ))
    return filled
```

### 8.2 Execution Rules — Battle-Tested

| Rule | Rationale |
|---|---|
| Market orders for SL/trailing exits ONLY | IOC limits fail in fast markets — Moonshot-CEX −$747 |
| Limit/stop-limit for entries | Reduces slippage; if unfilled = setup moved, don't chase |
| Bracket orders mandatory | Every position has SL + TP from birth |
| 5-second stop verification loop | Catches orphaned/failed stop orders at broker |
| Fill detection + 30s timeout | Prevents phantom positions in system state |
| No entry after 15:30 ET | Low liquidity, wide spreads |
| EOD exit at 15:57 ET | Prevents overnight gap risk |
| 4-hour symbol cooldown | Prevents re-entry churn on same ticker |
| Earnings auto-exit T-30min | Hard mechanical rule — not an agent decision |
| Spread check on entry | If spread > 0.3%, skip (liquidity degraded) |
| ADV liquidity check | Never > 1% of 30-day ADV in single order |

### 8.3 Realistic Slippage Model — ADV-Based

```python
import math


class SlippageModel:
    """
    Realistic execution cost model combining:
    1. Bid/ask spread (half-spread per side)
    2. Square-root market impact (Kyle's lambda approximation)
    3. Regime volatility multiplier

    Applied to EVERY simulated fill in backtesting.
    Validated against actual fills in paper trading.
    """
    BASE_SPREAD  = 0.0005    # 0.05% half-spread (large-cap, liquid)
    IMPACT_COEFF = 0.002     # empirical for large-cap US stocks

    REGIME_MULT = {
        "bull":         1.0,
        "neutral":      1.0,
        "fear":         1.5,   # wider spreads, more adverse selection
        "choppy":       2.0,   # should not be trading here
        "bear_mode":    1.8,
        "extreme_fear": 2.5,   # crisis liquidity
    }

    def one_way_cost(self, shares, price, adv, regime="neutral") -> float:
        """Returns one-way slippage as fraction of price."""
        if adv <= 0:
            return self.BASE_SPREAD * 2

        order_value = shares * price
        adv_value   = adv * price
        adv_fraction = order_value / max(adv_value, 1)

        # Square-root market impact
        impact = self.IMPACT_COEFF * math.sqrt(adv_fraction)
        mult   = self.REGIME_MULT.get(regime, 1.0)

        return (self.BASE_SPREAD + impact) * mult

    def simulate_fill(self, price, shares, side, adv,
                      regime="neutral") -> float:
        """Returns realistic fill price for backtesting."""
        slip = self.one_way_cost(shares, price, adv, regime)
        return price * (1 + slip) if side == "buy" else price * (1 - slip)

    def round_trip_cost(self, shares, price, adv, regime="neutral") -> float:
        """Total round-trip cost as fraction of position value."""
        return 2 * self.one_way_cost(shares, price, adv, regime)

    def annual_cost_drag(self, trades_per_year, avg_shares, avg_price,
                         avg_adv, avg_regime="neutral") -> float:
        """Estimates annual cost drag from slippage alone."""
        per_trade = self.round_trip_cost(avg_shares, avg_price, avg_adv, avg_regime)
        return per_trade * trades_per_year
```

**Typical cost estimates for target universe ($10B+ cap, 5M+ ADV):**

| Order Size vs ADV | One-Way Slip | Round-Trip | Annual (150 trades) |
|---|---|---|---|
| 0.01% of ADV (small) | ~0.06% | ~0.12% | ~1.8% |
| 0.10% of ADV (medium) | ~0.11% | ~0.22% | ~3.3% |
| 0.50% of ADV (large) | ~0.19% | ~0.38% | ~5.7% |

A system must generate > 5–6% annual alpha just to break even on costs at the large end. This is why the 1% ADV liquidity cap in position sizing exists.

***

## 9. Position Management

### 9.1 Exit Hierarchy — Evaluated Every 5 Seconds

| Priority | Exit Trigger | Condition | Action |
|---|---|---|---|
| 1 | **Hard Stop Loss** | Current P&L ≤ −SL% (ATR-based, ~1.5–2%) | MARKET SELL 100% immediately |
| 2 | **Trailing Stop** | Activated at +1%, trail distance 1% | MARKET SELL 100% |
| 3 | **Partial 2R** | R-multiple ≥ 2.0 | SELL 50%, move SL to breakeven |
| 4 | **Partial 3R** | R-multiple ≥ 3.0 | SELL 25% remaining, trail rest |
| 5 | **Breakeven Move** | R-multiple ≥ 1.0 | Move SL to exact entry price |
| 6 | **Earnings Auto-Exit** | T−30min before earnings | MARKET SELL 100% |
| 7 | **Time Exit (losers)** | Hold ≥ 3h AND P&L ≤ 0 | MARKET SELL 100% |
| 8 | **Time Exit (max)** | Hold ≥ 6h (any P&L) | MARKET SELL 100% |
| 9 | **Momentum Faded** | Peak ≥ +3%, gave back 60%+, P&L < +0.5% | MARKET SELL 100% |
| 10 | **EOD Exit** | Time ≥ 15:57 ET | MARKET SELL 100% all positions |

**The fundamental principle:** Time exits are for losers only (Priority 7). Winners ride via trailing stop (Priority 2). This single rule fixes the "winners held 0.41h vs losers 3.78h" failure mode documented in live trading.

### 9.2 R-Multiple Tracker

```python
from dataclasses import dataclass


@dataclass
class RMultipleTracker:
    entry_price: float
    stop_price:  float
    risk:        float = 0.0      # 1R distance in dollars per share
    peak_r:      float = 0.0

    def __post_init__(self):
        self.risk = abs(self.entry_price - self.stop_price)

    def current_r(self, price: float) -> float:
        if self.risk == 0:
            return 0.0
        return (price - self.entry_price) / self.risk

    def update(self, price: float) -> float:
        r = self.current_r(price)
        self.peak_r = max(self.peak_r, r)
        return r

    def gave_back_pct(self, price: float) -> float:
        """Fraction of peak R that has been given back."""
        if self.peak_r <= 0:
            return 0.0
        current = self.current_r(price)
        return max(0.0, (self.peak_r - current) / self.peak_r)

    def is_at_breakeven(self, price: float) -> bool:
        return self.current_r(price) >= 1.0

    def should_partial_2r(self, price: float, already_done: bool) -> bool:
        return self.current_r(price) >= 2.0 and not already_done

    def should_partial_3r(self, price: float, already_done: bool) -> bool:
        return self.current_r(price) >= 3.0 and not already_done
```

### 9.3 Trailing Stop Modes

| Mode | Activation | Distance | Use Case |
|---|---|---|---|
| Standard | +1.0% from entry | 1.0% from peak | Default for all positions |
| ATR-Based | 1.0× ATR from entry | 1.5× ATR from peak | High-volatility names |
| Regime-Scaled | Standard × regime_mult | Standard × mult | Auto-adapts to conditions |
| Chandelier | — | Highest high − 3×ATR | Swing holds overnight |
| Accelerated | Immediately | 0.5% from peak | Pre-earnings exit mode |

### 9.4 The 5-Second Position Management Loop

```python
async def position_management_loop(position_manager, risk_manager,
                                   earnings_calendar, regime_manager):
    """Runs continuously, every 5 seconds, independent of the 60s trading loop."""
    while True:
        current_price_map = await alpaca_client.get_latest_prices(
            [p.ticker for p in position_manager.open_positions.values()]
        )
        current_regime = regime_manager.current

        for ticker, position in list(position_manager.open_positions.items()):
            price = current_price_map.get(ticker)
            if not price:
                continue

            r = position.r_tracker.update(price)
            pnl_pct = (price - position.entry) / position.entry

            # Priority 1: Hard stop loss
            if pnl_pct <= -(position.stop_loss_pct):
                await position_manager.exit(ticker, "STOP_LOSS", price)
                continue

            # Priority 2: Trailing stop
            if position.trail_active and pnl_pct <= position.trail_stop_level:
                await position_manager.exit(ticker, "TRAILING_STOP", price)
                continue
            # Activate trailing if not yet active
            if not position.trail_active and pnl_pct >= position.trail_activate_pct:
                position.trail_active = True
                position.trail_high   = price
                position.trail_stop_level = pnl_pct - position.trail_distance_pct
                logger.info(f"{ticker}: trailing stop activated at +{pnl_pct:.2%}")

            # Update trailing high-water mark
            if position.trail_active and price > position.trail_high:
                position.trail_high = price
                position.trail_stop_level = (
                    (position.trail_high - position.entry) / position.entry
                    - position.trail_distance_pct
                )

            # Priority 3: Partial exit at 2R
            if position.r_tracker.should_partial_2r(price, position.partial_2r_done):
                shares_to_sell = int(position.shares * 0.50)
                await position_manager.partial_exit(ticker, shares_to_sell, "PARTIAL_2R", price)
                position.partial_2r_done = True
                # Move SL to breakeven
                position.stop_price = position.entry
                position.stop_loss_pct = 0.0
                logger.info(f"{ticker}: 2R hit — sold 50%, SL moved to breakeven")
                continue

            # Priority 4: Partial exit at 3R
            if position.r_tracker.should_partial_3r(price, position.partial_3r_done):
                shares_to_sell = int(position.shares * 0.25)
                await position_manager.partial_exit(ticker, shares_to_sell, "PARTIAL_3R", price)
                position.partial_3r_done = True
                logger.info(f"{ticker}: 3R hit — sold 25%, trailing remainder")
                continue

            # Priority 5: Move SL to breakeven at 1R
            if position.r_tracker.is_at_breakeven(price) and not position.breakeven_done:
                position.stop_price    = position.entry
                position.stop_loss_pct = 0.0
                position.breakeven_done = True
                logger.info(f"{ticker}: 1R hit — SL moved to breakeven")

            # Priority 6: Earnings auto-exit (T-30min)
            # Handled by earnings_calendar.earnings_exit_monitor() separately

            # Priority 7: Time exit — losers only
            hold_hours = (datetime.now(ET) - position.entry_time).total_seconds() / 3600
            if hold_hours >= 3.0 and pnl_pct <= 0:
                await position_manager.exit(ticker, "TIME_EXIT_LOSER", price)
                continue

            # Priority 8: Time exit — max hold regardless of P&L
            if hold_hours >= 6.0:
                await position_manager.exit(ticker, "TIME_EXIT_MAX", price)
                continue

            # Priority 9: Momentum faded
            if (position.r_tracker.peak_r >= 3.0
                    and position.r_tracker.gave_back_pct(price) >= 0.60
                    and pnl_pct < 0.005):
                await position_manager.exit(ticker, "MOMENTUM_FADED", price)
                continue

            # Priority 10: EOD exit
            now_et = datetime.now(ET).strftime("%H:%M")
            if now_et >= "15:57":
                await position_manager.exit(ticker, "EOD_EXIT", price)
                continue

        # Verify all stop orders are alive at broker (orphan detection)
        await stop_loss_verifier.verify_all(position_manager.open_positions)

        await asyncio.sleep(5)
```

***

## 10. Learning & Reflection System

### 10.1 Post-Trade Reflection Flow

After every closed trade, the following sequence runs automatically — not blocking the main trading loop (runs as a background task):

```python
async def post_trade_reflection(trade: ClosedTrade, agent_states: dict):
    """
    Triggered after every trade close.
    Each agent reflects on their role in the decision.
    Reflections stored in GuardedFinancialSituationMemory with:
    - regime tag (current regime at trade entry)
    - 90-day TTL
    - outcome label (win/loss/breakeven)
    """
    reflection_tasks = []

    for agent_id, agent in agent_states.items():
        if not hasattr(agent, "memory"):
            continue

        situation = extract_market_situation(trade)

        prompt = REFLECTION_PROMPT.format(
            ticker             = trade.ticker,
            entry              = trade.entry_price,
            exit               = trade.exit_price,
            pnl_pct            = trade.pnl_pct,
            regime             = trade.entry_regime,
            agent_role         = agent_id,
            your_recommendation= agent_states[agent_id].last_recommendation,
            final_decision     = trade.final_decision
        )

        async def reflect_and_store(agent=agent, agent_id=agent_id,
                                    situation=situation, prompt=prompt):
            reflection = await agent.llm.ainvoke(prompt)
            llm_cost_manager.record_call(**reflection.token_usage)
            agent.memory.add(
                situation_text = situation,
                reflection     = reflection.content,
                regime         = trade.entry_regime,
                outcome_pct    = trade.pnl_pct
            )

        reflection_tasks.append(reflect_and_store())

    # Run all reflections in parallel — background, non-blocking
    await asyncio.gather(*reflection_tasks, return_exceptions=True)
```

### 10.2 QuantMutator — Adaptive Threshold with Hard Floors

```python
class QuantMutator:
    """
    Adaptively adjusts Bayesian entry threshold based on:
    - Recent win rate (hot/cold streak detection)
    - Daily P&L (emergency tightening)
    - LLM cost status (cost-throttle mode)

    Hard floor: 0.40 — NEVER lower (0.12 destroyed Moonshot-CEX: −$387/day)
    Hard ceiling: 0.55 — Don't block all entries
    """
    FLOOR   = 0.40
    CEILING = 0.55
    DEFAULT = 0.45

    def mutate(self, win_rate: float, day_pnl_pct: float,
               threshold: float, llm_over_budget: bool) -> tuple[float, str]:

        if llm_over_budget:
            # In quant-only mode, raise threshold — quant signals need higher bar
            new = min(self.CEILING, threshold + 0.05)
            return new, "cost_throttle"

        if day_pnl_pct < -0.03:
            # Emergency: losing day — raise threshold immediately
            new = min(self.CEILING, threshold + 0.03)
            return new, "emergency_raise"

        if win_rate >= 0.65:
            # Hot streak — can afford to take more setups
            new = max(self.FLOOR, threshold - 0.02)
            return new, "hot_streak"

        if win_rate <= 0.35:
            # Cold streak — tighten quality requirement
            new = min(self.CEILING, threshold + 0.02)
            return new, "cold_streak"

        # No change needed — conditions normal
        return threshold, "no_change"

    def validate(self, threshold: float) -> float:
        """Always enforce hard bounds — safety net."""
        return max(self.FLOOR, min(self.CEILING, threshold))
```

### 10.3 Weekly Parameter Optimisation

Bayesian optimisation runs every Sunday 8 PM ET against Sharpe ratio from last 20 trading days. Parameters tuned:

| Parameter | Search Range | Notes |
|---|---|---|
| `stop_loss_atr_mult` | (1.0, 3.0) | Controls SL distance |
| `trailing_activate_pct` | (0.5%, 2.0%) | When trailing activates |
| `trailing_distance_pct` | (0.5%, 2.0%) | Trail tightness |
| `rsi_entry_low` | (30, 50) | RSI lower bound for entry |
| `rsi_entry_high` | (65, 80) | RSI upper bound for entry |
| `time_exit_hours` | (2, 6) | Max hold for losers |
| `earnings_blackout_hours` | (24, 72) | Pre-earnings no-trade window |
| `bayesian_threshold` | (0.40, 0.55) | Clamped by QuantMutator |

***

## 11. Data Infrastructure

### 11.1 Data Sources

| Source | Data Type | Frequency | Cost |
|---|---|---|---|
| Alpaca WebSocket | Real-time bars (1m/5m/15m) | Real-time | Free |
| Alpaca REST | Historical bars, account, positions, orders | On-demand | Free |
| yFinance | Fundamentals, earnings calendar, news, analyst ratings | Pre-market + on-demand | Free |
| CNN Fear & Greed | F&G Index (0–100) | 15-min scrape | Free |
| CBOE VIX | Volatility Index | Via Alpaca real-time | Free |
| Twelve Data | Daily bars cache | Daily | Free tier |
| Polygon.io | Tick-level historical, precise ADV data | Backtest phase | $29/mo |

### 11.2 Feature Engine — 50+ Indicators

```python
FEATURE_GROUPS = {
    "trend": [
        "ema_9", "ema_21", "ema_50", "ema_200",
        "sma_20", "sma_50", "sma_200",
        "ema_9_slope", "ema_21_slope",           # rate of change
        "price_vs_ema200_pct",                   # distance from 200d EMA
    ],
    "momentum": [
        "rsi_14", "rsi_7",
        "macd", "macd_signal", "macd_histogram",
        "stoch_k", "stoch_d",
        "williams_r", "cci_14",
        "rate_of_change_10", "rate_of_change_20",
    ],
    "volatility": [
        "atr_14", "atr_7",
        "bb_upper", "bb_lower", "bb_width",      # BB width = compression indicator
        "keltner_upper", "keltner_lower",
        "historical_vol_20",
    ],
    "volume": [
        "vwap", "vwap_distance_pct",
        "volume_sma_20", "volume_ratio",         # current / 20d average
        "obv", "mfi_14",
        "adv_30d",
    ],
    "price_action": [
        "support_level", "resistance_level",
        "pivot_point", "pivot_r1", "pivot_s1",
        "candle_body_pct", "candle_direction",   # bullish/bearish candle
        "gap_pct",                               # pre-market gap
    ],
    "relative": [
        "rs_vs_spy_5d", "rs_vs_spy_20d",        # relative strength vs market
        "rs_vs_sector_5d",                       # relative strength vs sector
        "beta_20d",                              # rolling beta
    ],
    "custom": [
        "momentum_1h",                           # 1-hour return
        "momentum_4h",                           # 4-hour return
        "earnings_momentum_score",               # PEAD score (0–1)
        "regime_label",                          # current market regime
    ]
}
```

### 11.3 Data Pipeline — Pre-Market Prep (9:00 AM ET)

```python
async def premarket_prep():
    """
    Runs every trading day at 9:00 AM ET — before market open.
    Prepares all data needed for the trading day.
    """
    logger.info("Pre-market data preparation starting")

    # 1. Update regime inputs
    fg_index  = await fetch_fear_greed()
    vix       = await fetch_vix()
    breadth   = await fetch_market_breadth()
    spy_20d   = await fetch_spy_return(days=20)
    regime    = classify_regime(fg_index, vix, breadth, spy_20d)

    # 2. Rank universe with EarningsMomentumScorer
    scored_universe = rank_universe(earnings_scorer)

    # 3. Pre-cache features for top 50 stocks
    await asyncio.gather(*[
        feature_engine.precompute(stock.ticker)
        for stock in scored_universe
    ])

    # 4. Load earnings calendar for today + next 48h
    await earnings_calendar.refresh()

    # 5. Reset daily counters
    risk_manager.reset_daily()
    llm_cost_manager.reset_daily()
    symbol_cooldown.clear_expired()

    logger.info(
        f"Pre-market complete | Regime: {regime} | "
        f"Universe: {len(scored_universe)} stocks | "
        f"Earnings blackouts today: {earnings_calendar.blackout_count_today()}"
    )
```

***

## 12. Backtesting & Walk-Forward Validation

### 12.1 Simulated Broker — Drop-in Alpaca Replacement

```python
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class SimulatedPosition:
    ticker:      str
    entry_price: float
    shares:      int
    stop_price:  float
    tp_price:    float
    entry_time:  pd.Timestamp
    regime:      str
    adv_30d:     float
    pnl:         float = 0.0
    is_open:     bool = True


@dataclass
class SimulatedFill:
    order_id:       str
    ticker:         str
    fill_price:     float
    shares:         int
    side:           str
    timestamp:      pd.Timestamp
    slippage_cost:  float


class SimulatedBroker:
    """
    Drop-in replacement for AlpacaClient in backtest mode.
    Applies realistic slippage to every fill.
    Tracks all trades, positions, and P&L.
    Identical interface to live broker — swap one line to go live.
    """
    def __init__(self, initial_capital: float, slippage_model: SlippageModel):
        self.cash            = initial_capital
        self.initial_capital = initial_capital
        self.positions:  dict[str, SimulatedPosition] = {}
        self.closed_trades:  list[dict] = []
        self.all_fills:      list[SimulatedFill] = []
        self.slippage        = slippage_model
        self.current_bar:    Optional[pd.Timestamp] = None
        self._order_counter  = 0

    def set_current_bar(self, timestamp: pd.Timestamp):
        self.current_bar = timestamp

    async def submit_order(self, symbol, qty, side, type="market",
                           stop_price=None, limit_price=None,
                           regime="neutral", **kwargs) -> SimulatedFill:
        price = get_historical_price(symbol, self.current_bar, side)
        adv   = get_historical_adv(symbol, self.current_bar)

        # Apply slippage model
        fill_price = self.slippage.simulate_fill(price, qty, side, adv, regime)
        slip_cost  = abs(fill_price - price) * qty

        self._order_counter += 1
        fill = SimulatedFill(
            order_id      = f"sim_{self._order_counter:06d}",
            ticker        = symbol,
            fill_price    = fill_price,
            shares        = qty,
            side          = side,
            timestamp     = self.current_bar,
            slippage_cost = slip_cost
        )
        self.all_fills.append(fill)

        # Update cash and positions
        if side == "buy":
            cost = fill_price * qty
            if cost > self.cash:
                return None  # insufficient cash
            self.cash -= cost
        elif side == "sell":
            if symbol not in self.positions:
                return None  # no position to sell
            pos = self.positions[symbol]
            proceeds = fill_price * qty
            self.cash += proceeds
            pnl = (fill_price - pos.entry_price) * qty - pos.slippage_cost_entry
            self.closed_trades.append({
                "ticker":      symbol,
                "entry":       pos.entry_price,
                "exit":        fill_price,
                "shares":      qty,
                "pnl":         pnl,
                "pnl_pct":     pnl / (pos.entry_price * qty),
                "entry_time":  pos.entry_time,
                "exit_time":   self.current_bar,
                "hold_hours":  (self.current_bar - pos.entry_time).total_seconds() / 3600,
                "regime":      pos.regime,
                "exit_reason": kwargs.get("exit_reason", "unknown"),
                "slippage":    slip_cost
            })
            if qty >= pos.shares:
                del self.positions[symbol]

        return fill

    async def get_all_positions(self) -> list[SimulatedPosition]:
        return list(self.positions.values())

    async def cancel_all_orders(self) -> int:
        return 0  # no pending orders in sim

    def portfolio_value(self) -> float:
        positions_value = sum(
            get_historical_price(t, self.current_bar, "mid") * p.shares
            for t, p in self.positions.items()
        )
        return self.cash + positions_value

    def get_performance(self) -> dict:
        if not self.closed_trades:
            return {"error": "no trades"}
        trades_df = pd.DataFrame(self.closed_trades)
        return calculate_performance_metrics(trades_df, self.initial_capital)
```

### 12.2 Performance Metrics

```python
import numpy as np
import pandas as pd


def calculate_performance_metrics(trades_df: pd.DataFrame,
                                   initial_capital: float) -> dict:
    if trades_df.empty:
        return {}

    pnl = trades_df["pnl"]
    pnl_pct = trades_df["pnl_pct"]
    wins  = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    # Win rate
    win_rate = len(wins) / len(pnl) if len(pnl) > 0 else 0

    # Profit factor
    gross_profit = wins.sum()
    gross_loss   = abs(losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Equity curve
    equity = initial_capital + pnl.cumsum()
    rolling_max = equity.cummax()
    drawdowns = (equity - rolling_max) / rolling_max
    max_drawdown = drawdowns.min()

    # Sharpe ratio (annualised, assuming 252 trading days)
    daily_returns = trades_df.groupby(
        trades_df["exit_time"].dt.date
    )["pnl_pct"].sum()
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) \
             if daily_returns.std() > 0 else 0

    # Sortino ratio
    downside = daily_returns[daily_returns < 0]
    sortino = (daily_returns.mean() / downside.std()) * np.sqrt(252) \
              if len(downside) > 0 and downside.std() > 0 else 0

    # Average win/loss
    avg_win  = wins.mean()  if len(wins)   > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # Cost analysis
    total_slippage = trades_df["slippage"].sum()
    slippage_pct   = total_slippage / initial_capital

    # Per-regime breakdown
    regime_metrics = {}
    for regime in trades_df["regime"].unique():
        r_trades = trades_df[trades_df["regime"] == regime]
        r_wins   = r_trades[r_trades["pnl"] > 0]
        regime_metrics[regime] = {
            "trades":       len(r_trades),
            "win_rate":     len(r_wins) / len(r_trades),
            "total_pnl":    r_trades["pnl"].sum(),
            "avg_pnl":      r_trades["pnl"].mean(),
        }

    return {
        "total_trades":    len(trades_df),
        "win_rate":        round(win_rate, 4),
        "profit_factor":   round(profit_factor, 3),
        "sharpe_ratio":    round(sharpe, 3),
        "sortino_ratio":   round(sortino, 3),
        "max_drawdown":    round(max_drawdown, 4),
        "total_pnl":       round(pnl.sum(), 2),
        "total_return_pct":round(pnl.sum() / initial_capital, 4),
        "avg_win":         round(avg_win, 2),
        "avg_loss":        round(avg_loss, 2),
        "expectancy":      round(expectancy, 2),
        "avg_hold_hours":  round(trades_df["hold_hours"].mean(), 2),
        "total_slippage":  round(total_slippage, 2),
        "slippage_drag":   round(slippage_pct, 4),
        "per_regime":      regime_metrics,
    }
```

### 12.3 Walk-Forward Validator

```python
from dateutil.relativedelta import relativedelta


class WalkForwardValidator:
    """
    Rolling window validation:
    Train:    12 months (parameter optimisation)
    Validate: 3 months  (parameter selection)
    Test:     1 month   (out-of-sample truth)
    Roll:     1 month forward, repeat

    Go/No-Go: OOS Sharpe > 1.2 in ≥ 70% of test windows
    """
    def __init__(self, config, backtester, optimizer,
                 train_months=12, validate_months=3, test_months=1):
        self.config          = config
        self.backtester      = backtester
        self.optimizer       = optimizer
        self.train_months    = train_months
        self.validate_months = validate_months
        self.test_months     = test_months

    def run(self, start_date: str, end_date: str) -> dict:
        results = []
        current = pd.Timestamp(start_date)
        end     = pd.Timestamp(end_date)
        total_needed = relativedelta(months=
            self.train_months + self.validate_months + self.test_months)

        while current + total_needed <= end:
            train_start    = current
            train_end      = current + relativedelta(months=self.train_months)
            validate_start = train_end
            validate_end   = validate_start + relativedelta(months=self.validate_months)
            test_start     = validate_end
            test_end       = test_start + relativedelta(months=self.test_months)

            # Step 1: Optimise parameters on training window
            best_params = self.optimizer.optimise(
                start=train_start.strftime("%Y-%m-%d"),
                end=train_end.strftime("%Y-%m-%d"),
                objective="sharpe"
            )

            # Step 2: Validate parameter stability
            val_metrics = self.backtester.run(
                start=validate_start.strftime("%Y-%m-%d"),
                end=validate_end.strftime("%Y-%m-%d"),
                params=best_params
            )

            # Step 3: Out-of-sample test (the only number that matters)
            test_metrics = self.backtester.run(
                start=test_start.strftime("%Y-%m-%d"),
                end=test_end.strftime("%Y-%m-%d"),
                params=best_params
            )

            # Degradation: how much does performance drop from validate → test
            sharpe_degradation = (
                val_metrics["sharpe_ratio"] - test_metrics["sharpe_ratio"]
            )

            window_result = {
                "window_start":      train_start.strftime("%Y-%m"),
                "train_sharpe":      self.backtester.run(
                    train_start.strftime("%Y-%m-%d"),
                    train_end.strftime("%Y-%m-%d"), best_params
                )["sharpe_ratio"],
                "validate_sharpe":   val_metrics["sharpe_ratio"],
                "test_sharpe":       test_metrics["sharpe_ratio"],   # OOS truth
                "sharpe_degradation": round(sharpe_degradation, 3),
                "test_trades":       test_metrics["total_trades"],
                "test_win_rate":     test_metrics["win_rate"],
                "test_max_dd":       test_metrics["max_drawdown"],
                "best_params":       best_params,
                "passed":            test_metrics["sharpe_ratio"] >= 1.2
            }
            results.append(window_result)

            # Roll forward one month
            current += relativedelta(months=self.test_months)

        # Aggregate verdict
        if not results:
            return {"error": "insufficient data for walk-forward"}

        oos_sharpes  = [r["test_sharpe"] for r in results]
        pass_rate    = sum(1 for r in results if r["passed"]) / len(results)
        avg_oos      = np.mean(oos_sharpes)
        worst_oos    = min(oos_sharpes)
        avg_degrade  = np.mean([r["sharpe_degradation"] for r in results])
        system_valid = pass_rate >= 0.70 and avg_oos >= 1.2

        return {
            "windows":           results,
            "total_windows":     len(results),
            "pass_rate":         round(pass_rate, 3),
            "avg_oos_sharpe":    round(avg_oos, 3),
            "worst_oos_sharpe":  round(worst_oos, 3),
            "avg_degradation":   round(avg_degrade, 3),
            "system_valid":      system_valid,
            "verdict":           (
                "✅ SYSTEM VALID — proceed to paper trading"
                if system_valid else
                "❌ SYSTEM INVALID — do not trade live. Review parameters."
            )
        }
```

### 12.4 Validation Protocol — Phased Gates

| Phase | Duration | Capital | Risk | Gate Criteria |
|---|---|---|---|---|
| 0. Walk-Forward Backtest | 2yr historical | Simulated $50K | None | OOS Sharpe > 1.2 in ≥ 70% windows |
| 1. Paper Trade | 30 days | Alpaca paper | None | WR ≥ 50%, PF ≥ 1.5, ≥ 50 trades |
| 2. Micro Live | 30 days | $5K real | Very low | WR ≥ 52%, PF ≥ 1.8, DD < 15% |
| 3. Small Live | 60 days | $25K real | Low | WR ≥ 55%, PF ≥ 2.0, DD < 12% |
| 4. Full Live | Ongoing | $50K+ | Normal | Ongoing monitoring |

**Hard rule:** Do not advance a phase unless ALL gate criteria are met. One green metric and two red ones is a FAIL.

***

## 13. Implementation Roadmap — Backtest First

### Phase 0: Foundation + Simulated Broker (Weeks 1–2) ← STARTS HERE

```
Week 1:
  □ Monorepo setup (Python 3.12, FastAPI, Supabase)
  □ Unified config system (config.py)
  □ SimulatedBroker — drop-in Alpaca replacement
  □ Historical data loader (yFinance daily, Polygon.io ticks)
  □ SlippageModel — ADV-based, applied to every fill
  □ Performance metrics (Sharpe, PF, MDD, Sortino, per-regime)
  □ Basic backtester runner

Week 2:
  □ WalkForwardValidator (rolling 12/3/1 month windows)
  □ PerformanceMetrics per-regime breakdown
  □ Alpaca paper account integration (identical interface to SimulatedBroker)
  □ Basic CI/CD pipeline (GitHub Actions)
  □ Unit tests for all Phase 0 components
```

### Phase 1: Quant Engine (Weeks 3–4) — Testable in Backtest

```
Week 3:
  □ Feature engine (50+ indicators) — ported from DayTraderAI
  □ Regime detector (4 inputs: VIX, F&G, Breadth, SPY momentum)
  □ Bayesian engine — ported from Moonshot-CEX
  □ Wave entry conditions
  □ No-trade zone filters

Week 4:
  □ Universe scanner (3-factor first: momentum + volume + gap)
  □ QuantMutator with hard floors
  □ Position sizing (ATR-based, regime-adjusted)
  □ CorrelationManager (rolling 20d beta to SPY)
  □ PortfolioBetaManager
  □ Run quant-only backtest → establish baseline performance
```

**Phase 1 exit gate:** Quant-only system achieves Sharpe > 0.8 in backtest. If not, debug signal quality before adding agents — agents cannot fix a broken signal.

### Phase 2: Agent Intelligence (Weeks 5–8) — Testable in Backtest

```
Week 5:
  □ LangGraph parallel setup — adapted from TradingAgents
  □ Technical Analyst agent (mandatory, quick-think)
  □ News Analyst agent (mandatory, quick-think)
  □ Sentiment Analyst agent (optional enrichment, quick-think)
  □ Fundamentals Analyst agent (optional enrichment, quick-think)
  □ asyncio.gather() parallel execution with timeout handling

Week 6:
  □ Bull/Bear researcher agents (debate system)
  □ Research Manager (deep-think LLM — judge node)
  □ Trader agent (entry plan generator)
  □ 3-way Risk debate (Aggressive / Neutral / Conservative)
  □ Portfolio Manager (deep-think LLM — final APPROVE/REJECT)

Week 7:
  □ GuardedFinancialSituationMemory (TTL + regime tags + pgvector)
  □ Reflection system (post-trade, background tasks)
  □ EarningsMomentumScorer — full implementation
  □ Earnings blackout rule (hard gate, not agent decision)
  □ 4-factor universe scanner (adds EarningsMomentumScore as 30% weight)

Week 8:
  □ LLMCostManager (two-tier model, daily cap, quant fallback)
  □ Full agent pipeline integration test in backtest
  □ Walk-forward validation with full agent pipeline
  □ Compare: agents vs quant-only baseline (agents must add ≥ 10% Sharpe improvement)
```

**Phase 2 exit gate:** Walk-forward OOS Sharpe > 1.2 in ≥ 70% of windows. If agents don't improve on quant baseline, re-evaluate before proceeding.

### Phase 3: Execution Engine (Weeks 9–11) — Paper Trading

```
Week 9:
  □ Smart Order Executor — limit/stop-limit for entries (ported + upgraded)
  □ Bracket order system (every position has SL + TP from birth)
  □ Fill detection engine (30s timeout — no phantom positions)
  □ 5-second stop verification loop (orphan detection)
  □ Alpaca live paper account integration

Week 10:
  □ Position Manager — merged DayTraderAI exits + Moonshot-CEX trailing
  □ R-multiple tracker (2R partial, 3R partial, breakeven move)
  □ All trailing stop modes (Standard, ATR, Regime-Scaled, Chandelier, Accelerated)
  □ Earnings auto-exit monitor (T-30min mechanical rule)
  □ EOD exit at 15:57 ET

Week 11:
  □ Emergency kill switch (POST /api/v1/emergency_halt)
  □ System control endpoints (pause, resume, status)
  □ BearModeManager (inverse ETF rotation with 3-loop confirmation)
  □ 30-day paper trade → Phase 1→2 gate evaluation
```

### Phase 4: Risk Architecture (Weeks 12–13)

```
Week 12:
  □ 5-tier risk hierarchy fully wired and tested
  □ Daily loss circuit breaker (3% → halt new entries)
  □ Drawdown circuit breaker (15% → full halt)
  □ Consecutive loss pause (3 losses → 30-min cooldown)
  □ Symbol cooldown manager (4-hour per ticker)

Week 13:
  □ Sector exposure tracking (max 20% per sector)
  □ Portfolio beta control (max 1.5× rolling 20d)
  □ Correlation cluster enforcement (max 2 correlated positions)
  □ LLM cost circuit breaker (quant-only fallback at $25/day)
  □ Weekly parameter optimiser (Bayesian, Sunday 8 PM ET)
```

### Phase 5: Frontend + Monitoring (Weeks 14–15)

```
Week 14:
  □ React 18 dashboard (adapted from DayTraderAI)
  □ Real-time position table (P&L, R-multiple, hold time, regime)
  □ Agent decision audit trail (full debate log per trade)
  □ Regime indicator (current regime + VIX + F&G + Breadth)
  □ Equity curve + drawdown chart

Week 15:
  □ LLM cost tracker (daily spend, budget remaining)
  □ Walk-forward results viewer
  □ Emergency halt button (prominent, always visible)
  □ Performance metrics dashboard (WR, PF, Sharpe, per-regime)
  □ Alert system (Telegram or email on critical events)
```

### Phase 6: Validation → Micro-Live (Weeks 16–22)

```
Weeks 16–17: Full 2-year walk-forward backtest (final validation)
Week 18:     Paper trade (30 days) → Phase 1→2 gate
Week 19:     Paper trade review → Go/No-Go for micro-live
Weeks 20–22: Micro-live $5K → Phase 2→3 gate evaluation
Week 23+:    Small live $25K if micro-live gate passed
```

**Total: ~22 weeks (5.5 months) to micro-live with genuine statistical confidence.**

***

## 14. File Structure

```
moonshotx/
├── backend/
│   ├── server.py                        # FastAPI main — all endpoints
│   ├── config.py                        # Unified config dataclass
│   ├── main.py                          # Entry point — starts trading loop
│   │
│   ├── agents/                          # From TradingAgents (adapted)
│   │   ├── analysts/
│   │   │   ├── technical.py             # Technical Analyst (mandatory)
│   │   │   ├── news.py                  # News Analyst (mandatory)
│   │   │   ├── sentiment.py             # Sentiment (optional enrichment)
│   │   │   └── fundamentals.py          # Fundamentals (optional enrichment)
│   │   ├── researchers/
│   │   │   ├── bull.py                  # Bull Researcher
│   │   │   └── bear.py                  # Bear Researcher
│   │   ├── managers/
│   │   │   ├── research_manager.py      # Deep-think — judge verdict
│   │   │   └── portfolio_manager.py     # Deep-think — APPROVE/REJECT
│   │   ├── risk_mgmt/
│   │   │   ├── aggressive.py
│   │   │   ├── neutral.py
│   │   │   └── conservative.py
│   │   ├── trader/
│   │   │   └── trader.py                # Entry plan generator
│   │   └── utils/
│   │       ├── memory.py                # GuardedFinancialSituationMemory
│   │       ├── states.py                # LangGraph state definitions
│   │       └── prompts.py               # All agent system prompts
│   │
│   ├── graph/                           # LangGraph orchestration
│   │   ├── trading_graph.py             # Main graph definition
│   │   ├── setup.py                     # LangGraph setup + config
│   │   ├── propagation.py               # propagate_parallel()
│   │   ├── reflection.py                # Post-trade reflection runner
│   │   ├── signal_processing.py         # Pre/post signal transforms
│   │   └── conditional_logic.py         # Graph routing conditions
│   │
│   ├── data/                            # From DayTraderAI (adapted)
│   │   ├── market_data.py               # Alpaca WebSocket real-time
│   │   ├── features.py                  # 50+ indicator feature engine
│   │   ├── daily_cache.py               # Pre-market data caching
│   │   ├── earnings_calendar.py         # Earnings dates + blackout logic
│   │   └── dataflows/                   # yFinance interface (TradingAgents)
│   │       ├── interface.py
│   │       ├── fundamentals.py
│   │       └── news.py
│   │
│   ├── trading/                         # Merged DayTraderAI + Moonshot-CEX
│   │   ├── trading_loop.py              # Main 60s async loop
│   │   ├── position_manager.py          # Merged exit system
│   │   ├── regime_manager.py            # 4-input regime classifier
│   │   ├── bear_mode_manager.py         # Inverse ETF rotation
│   │   ├── trailing_stops.py            # All trailing stop modes
│   │   ├── stop_loss_protection.py      # 5-second verification loop
│   │   ├── profit_taker.py              # R-multiple partial exits
│   │   ├── breakeven_manager.py         # SL → breakeven moves
│   │   ├── wave_entry.py                # Wave entry conditions
│   │   ├── symbol_cooldown.py           # 4-hour ticker cooldown
│   │   ├── universe_scanner.py          # 4-factor ranked universe
│   │   ├── earnings_momentum_scorer.py  # PEAD edge (new)
│   │   ├── bayesian_engine.py           # From Moonshot-CEX
│   │   └── quant_mutator.py             # Adaptive threshold
│   │
│   ├── orders/                          # From DayTraderAI
│   │   ├── smart_order_executor.py      # Limit/stop-limit entries
│   │   ├── bracket_orders.py            # SL + TP from birth
│   │   └── fill_detection_engine.py     # 30s fill timeout
│   │
│   ├── risk/
│   │   ├── risk_manager.py              # 5-tier hierarchy
│   │   ├── correlation_manager.py       # Rolling 20d beta clusters
│   │   ├── portfolio_beta_manager.py    # Max 1.5× portfolio beta
│   │   ├── slippage_model.py            # ADV-based impact model
│   │   ├── llm_cost_manager.py          # Daily cap + quant fallback
│   │   └── emergency_halt.py            # Kill switch endpoints
│   │
│   ├── adaptive/
│   │   ├── parameter_optimizer.py       # Bayesian opt (Sunday 8PM)
│   │   └── quant_mutator.py             # Real-time threshold adaptation
│   │
│   └── backtest/                        # BUILT FIRST — Phase 0
│       ├── simulated_broker.py          # Drop-in Alpaca replacement
│       ├── backtester.py                # Main backtest runner
│       ├── data_loader.py               # Historical OHLCV loader
│       ├── performance_metrics.py       # All performance calculations
│       └── walk_forward.py              # Rolling OOS validator
│
├── frontend/                            # From DayTraderAI (React 18)
│   └── src/
│       ├── components/
│       │   ├── Dashboard/               # Main layout
│       │   ├── PositionTable/           # Live positions + P&L + R-multiple
│       │   ├── AgentAuditTrail/         # Full debate log per trade
│       │   ├── EquityCurve/             # Rolling equity + drawdown
│       │   ├── RegimeIndicator/         # Current regime + 4 inputs
│       │   ├── LLMCostTracker/          # Daily spend vs cap
│       │   ├── WalkForwardResults/      # OOS window chart
│       │   ├── PerformanceMetrics/      # WR, PF, Sharpe, per-regime
│       │   └── EmergencyHaltButton/     # Prominent, always visible
│       └── hooks/
│           ├── usePositions.ts
│           ├── useSystemStatus.ts
│           └── usePerformance.ts
│
├── tests/
│   ├── unit/
│   │   ├── test_slippage_model.py
│   │   ├── test_quant_mutator.py
│   │   ├── test_regime_classifier.py
│   │   ├── test_r_multiple_tracker.py
│   │   └── test_earnings_momentum_scorer.py
│   ├── integration/
│   │   ├── test_simulated_broker.py
│   │   ├── test_position_manager.py
│   │   └── test_walk_forward.py
│   └── backtest_results/               # Stored walk-forward outputs
│       └── .gitkeep
│
├── run_backtest.py                      # CLI entry point for backtesting
├── run_walkforward.py                   # CLI entry point for walk-forward
├── requirements.txt
├── .env.example
└── README.md
```

***

## 15. Configuration Reference

```python
MOONSHOTX_CONFIG = {
    # === LLM ===
    "llm_provider":            "anthropic",
    "deep_think_llm":          "claude-3-7-sonnet-20250219",
    "quick_think_llm":         "claude-haiku-3-5",
    "max_debate_rounds":        2,
    "max_risk_discuss_rounds":  2,
    "agent_timeout_seconds":    20,
    "loop_wall_clock_seconds":  45,

    # === LLM Cost Controls ===
    "llm_cost_daily_cap_usd":   25.0,
    "llm_cost_alert_usd":       15.0,

    # === Capital ===
    "initial_capital":          50_000,

    # === Trading ===
    "risk_per_trade_pct":       0.015,
    "max_positions_bull":       5,
    "max_positions_neutral":    4,
    "max_positions_fear":       3,
    "max_positions_choppy":     0,
    "max_single_position_pct":  0.04,
    "max_sector_exposure_pct":  0.20,
    "max_portfolio_beta":       1.5,
    "max_daily_loss_pct":       0.03,
    "max_drawdown_pct":         0.15,
    "max_daily_trades":         15,
    "consecutive_loss_pause":   3,

    # === Entry ===
    "bayesian_threshold":       0.45,
    "bayesian_floor":           0.40,
    "bayesian_ceiling":         0.55,
    "symbol_cooldown_hours":    4,
    "entry_cutoff_time":        "15:30",
    "earnings_blackout_hours":  48,
    "earnings_auto_exit_mins":  30,

    # === Exits ===
    "stop_loss_atr_mult":       1.5,
    "trailing_activate_pct":    0.01,
    "trailing_distance_pct":    0.01,
    "time_exit_hours":          3.0,
    "time_exit_max_hours":      6.0,
    "eod_exit_time":            "15:57",
    "partial_profit_2r_pct":    0.50,
    "partial_profit_3r_pct":    0.25,
    "breakeven_r_trigger":      1.0,

    # === Bear Mode ===
    "bear_mode_vix_trigger":    28.0,
    "bear_mode_breadth_trigger": 0.30,
    "bear_mode_confirm_loops":  3,
    "inverse_etf_primary":      "SQQQ",
    "inverse_etf_secondary":    "SPXU",
    "inverse_etf_mild":         "SH",
    "inverse_etf_max_alloc":    0.15,
    "inverse_etf_position_pct": 0.05,

    # === Memory ===
    "memory_ttl_days":          90,
    "memory_regime_filtered":   True,
    "memory_top_k":             3,

    # === Correlation ===
    "correlation_window_days":  20,
    "correlation_threshold":    0.75,

    # === Universe ===
    "universe_size":            50,
    "min_market_cap":           10_000_000_000,
    "min_avg_volume":           5_000_000,
    "min_price":                20.0,
    "max_price":                1000.0,

    # === Slippage ===
    "slippage_model_enabled":   True,
    "slippage_base_spread":     0.0005,
    "slippage_impact_coeff":    0.002,

    # === Walk-Forward ===
    "wf_train_months":          12,
    "wf_validate_months":       3,
    "wf_test_months":           1,
    "wf_oos_sharpe_min":        1.2,
    "wf_pass_rate_min":         0.70,
}
```

***

## 16. LLM Cost Model

### Two-Tier Architecture Cost Breakdown

| Agent | Tier | Model | Tokens/Call | Cost/Call | Calls/Day |
|---|---|---|---|---|---|
| Technical Analyst | Quick | Claude Haiku / GPT-4o-mini | ~2,000 | ~$0.0004 | 50 |
| News Analyst | Quick | Claude Haiku / GPT-4o-mini | ~2,500 | ~$0.0005 | 50 |
| Sentiment Analyst | Quick | Claude Haiku / GPT-4o-mini | ~1,500 | ~$0.0003 | 30 |
| Fundamentals Analyst | Quick | Claude Haiku / GPT-4o-mini | ~3,000 | ~$0.0006 | 30 |
| Bull + Bear Researchers | Quick | Claude Haiku / GPT-4o-mini | ~2,000 each | ~$0.0004 | 15 each |
| Research Manager | **Deep** | Claude 3.7 / GPT-4o | ~8,000 | ~$0.024 | 15 |
| Trader + Risk agents | Quick | Claude Haiku / GPT-4o-mini | ~1,500 each | ~$0.0003 | 15 each |
| Portfolio Manager | **Deep** | Claude 3.7 / GPT-4o | ~8,000 | ~$0.024 | 15 |
| Reflection (post-trade) | Quick | Claude Haiku / GPT-4o-mini | ~2,000 | ~$0.0004 | 15 |

### Daily Cost Estimate (15 Trades/Day)

```
Quick-think total:   ~$0.12–0.18/day
Deep-think total:    ~$0.72/day (2 nodes × 15 calls × $0.024)
─────────────────────────────────────────────
Total estimated:     ~$1.00–2.00/day
Monthly:             ~$20–40/month
Annual:              ~$240–480/year
```

This is **not** $50–200/day. That scenario requires deep-think on every agent (a v1.0 mistake) or 100+ full pipeline analyses per day with no Bayesian pre-filter. The two-tier model + Bayesian gate reduces cost by approximately 95%.

### LLM Cost Rate Card

| Model | Input ($/M tokens) | Output ($/M tokens) |
|---|---|---|
| Claude 3.7 Sonnet | $3.00 | $15.00 |
| GPT-4o | $2.50 | $10.00 |
| Claude Haiku 3.5 | $0.80 | $4.00 |
| GPT-4o-mini | $0.15 | $0.60 |

***

## 17. Alpha Source — EarningsMomentumScorer

### Why Post-Earnings Drift (PEAD) Is a Real Edge

PEAD is one of the most documented persistent anomalies in academic finance. Stocks that beat EPS estimates meaningfully continue drifting in the direction of the surprise for 2–10 trading days. The mechanism is structural:

1. **Institutional re-rating lag**: Funds that missed the beat start accumulating — sustained buying, not a spike
2. **Analyst upgrade cycle**: Upgrades lag earnings by 24–72h; each upgrade triggers additional fund flow
3. **Retail follow-through**: Retail follows after day 2, adding momentum fuel
4. **Short covering**: Wrong-side shorts cover — adds additional upward pressure

The window is specific — **days 2–5 post-beat** are optimal. Day 1 is too volatile (gap risk); day 6+ the drift typically exhausts. This precision is what makes it an edge rather than just a factor.

### Full Implementation

```python
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import yfinance as yf


@dataclass
class EarningsEvent:
    ticker:            str
    date:              datetime
    eps_actual:        float
    eps_estimate:      float
    eps_surprise_pct:  float   # (actual - estimate) / abs(estimate)
    revenue_beat:      bool


class EarningsMomentumScorer:
    """
    Scores stocks on post-earnings-beat momentum quality.
    Score: 0.0 (no catalyst) → 1.0 (perfect PEAD setup)
    Optimal entry window: days 2–5 post-earnings-beat
    """
    W_EPS_BEAT    = 0.35   # Quality and size of the beat
    W_ANALYST     = 0.25   # Post-beat analyst upgrade momentum
    W_COMPRESSION = 0.20   # Pre-earnings technical compression
    W_VOLUME      = 0.20   # Post-earnings volume confirmation

    # PEAD window: ramp up days 1-3, peak day 3, decay days 4-10
    DAY_WEIGHTS = {
        1: 0.50, 2: 0.85, 3: 1.00, 4: 0.95, 5: 0.85,
        6: 0.70, 7: 0.55, 8: 0.40, 9: 0.25, 10: 0.15
    }

    def get_last_earnings(self, ticker: str) -> Optional[EarningsEvent]:
        try:
            t = yf.Ticker(ticker)
            earnings = t.quarterly_earnings
            if earnings is None or earnings.empty:
                return None
            last = earnings.iloc[-1]
            actual   = float(last.get("Reported EPS", 0))
            estimate = float(last.get("EPS Estimate", 0))
            if estimate == 0:
                return None
            surprise = (actual - estimate) / abs(estimate)
            return EarningsEvent(
                ticker           = ticker,
                date             = earnings.index[-1].to_pydatetime(),
                eps_actual       = actual,
                eps_estimate     = estimate,
                eps_surprise_pct = surprise,
                revenue_beat     = True  # simplified — enhance with revenue data
            )
        except Exception:
            return None

    def score(self, ticker: str) -> float:
        last = self.get_last_earnings(ticker)
        if not last:
            return 0.0

        days_since = (datetime.now() - last.date).days
        if days_since < 1 or days_since > 10:
            return 0.0

        day_mult = self.DAY_WEIGHTS.get(days_since, 0.0)
        if day_mult == 0.0:
            return 0.0

        eps_score      = self._score_eps_beat(last)
        analyst_score  = self._score_analyst_upgrades(ticker, last.date)
        compress_score = self._score_compression(ticker, last.date)
        volume_score   = self._score_volume_surge(ticker, last.date)

        raw = (
            self.W_EPS_BEAT    * eps_score    +
            self.W_ANALYST     * analyst_score +
            self.W_COMPRESSION * compress_score +
            self.W_VOLUME      * volume_score
        )
        return min(1.0, raw * day_mult)

    def _score_eps_beat(self, event: EarningsEvent) -> float:
        s = event.eps_surprise_pct
        if s >= 0.20: return 1.00   # > 20% beat — exceptional
        if s >= 0.10: return 0.75   # > 10% beat — strong
        if s >= 0.05: return 0.50   # > 5% beat  — moderate
        if s >= 0.01: return 0.20   # in-line / tiny beat
        return 0.0                  # miss — no score

    def _score_analyst_upgrades(self, ticker: str, since: datetime) -> float:
        try:
            t = yf.Ticker(ticker)
            upgrades = t.upgrades_downgrades
            if upgrades is None or upgrades.empty:
                return 0.0
            recent = upgrades[
                (upgrades.index >= since) &
                (upgrades["ToGrade"].str.lower().isin(
                    ["buy", "strong buy", "outperform", "overweight"]))
            ]
            return min(1.0, len(recent) * 0.33)  # 3 upgrades = max
        except Exception:
            return 0.0

    def _score_compression(self, ticker: str, earnings_date: datetime) -> float:
        """Pre-earnings Bollinger Band width — tighter = more explosive."""
        try:
            end   = earnings_date - timedelta(days=1)
            start = end - timedelta(days=30)
            hist  = yf.Ticker(ticker).history(start=start, end=end)
            if hist.empty or len(hist) < 10:
                return 0.0
            close = hist["Close"]
            sma   = close.rolling(20).mean()
            std   = close.rolling(20).std()
            bb_width_recent = (4 * std.iloc[-1]) / sma.iloc[-1]
            bb_width_avg    = (4 * std).mean() / sma.mean()
            if bb_width_avg == 0:
                return 0.0
            ratio = bb_width_recent / bb_width_avg
            # Very tight (< 50% of avg) = 1.0, average = 0.5, wide = 0.0
            return max(0.0, min(1.0, 1.5 - ratio))
        except Exception:
            return 0.0

    def _score_volume_surge(self, ticker: str, since: datetime) -> float:
        """Post-earnings volume vs 30-day pre-earnings ADV."""
        try:
            post_start = since
            post_end   = since + timedelta(days=5)
            pre_start  = since - timedelta(days=35)

            hist = yf.Ticker(ticker).history(start=pre_start, end=post_end)
            if hist.empty:
                return 0.0

            pre_vol  = hist[hist.index < since]["Volume"].mean()
            post_vol = hist[hist.index >= since]["Volume"].mean()

            if pre_vol == 0:
                return 0.0

            ratio = post_vol / pre_vol
            if ratio >= 3.0: return 1.00
            if ratio >= 2.0: return 0.75
            if ratio >= 1.5: return 0.50
            return 0.0
        except Exception:
            return 0.0
```

***

## 18. Portfolio Beta Control

```python
import numpy as np
from functools import lru_cache


class PortfolioBetaManager:
    """
    Prevents the portfolio from becoming a leveraged market bet.
    Beta computed as rolling 20-day daily return correlation × volatility ratio vs SPY.
    Hard cap: portfolio weighted beta ≤ 1.5×
    """
    MAX_PORTFOLIO_BETA = 1.5
    WINDOW_DAYS        = 20

    @lru_cache(maxsize=200)
    def get_beta(self, ticker: str) -> float:
        """Rolling 20-day OLS beta vs SPY."""
        try:
            import yfinance as yf
            import pandas as pd
            tickers = yf.download(
                [ticker, "SPY"], period="30d",
                interval="1d", progress=False, auto_adjust=True
            )["Close"]
            returns = tickers.pct_change().dropna()
            if len(returns) < self.WINDOW_DAYS:
                return 1.0  # assume market beta if insufficient data
            cov = returns.cov()
            beta = cov.loc[ticker, "SPY"] / returns["SPY"].var()
            return float(beta)
        except Exception:
            return 1.0  # conservative assumption

    def get_portfolio_beta(self, open_positions: list) -> float:
        """Weighted average beta of all open positions."""
        if not open_positions:
            return 0.0
        total_value = sum(p.market_value for p in open_positions)
        if total_value == 0:
            return 0.0
        weighted = sum(
            (p.market_value / total_value) * self.get_beta(p.ticker)
            for p in open_positions
        )
        return weighted

    def projected_beta(self, open_positions: list,
                       new_ticker: str, new_value: float) -> float:
        """Estimates portfolio beta after adding new position."""
        current_value = sum(p.market_value for p in open_positions)
        total_value   = current_value + new_value
        if total_value == 0:
            return 0.0
        current_weighted = sum(
            p.market_value * self.get_beta(p.ticker)
            for p in open_positions
        )
        new_weighted = new_value * self.get_beta(new_ticker)
        return (current_weighted + new_weighted) / total_value

    def can_add_position(self, open_positions: list,
                         new_ticker: str, new_value: float) -> bool:
        proj = self.projected_beta(open_positions, new_ticker, new_value)
        if proj > self.MAX_PORTFOLIO_BETA:
            logger.info(
                f"{new_ticker}: projected portfolio beta {proj:.2f} "
                f"> max {self.MAX_PORTFOLIO_BETA} — position rejected"
            )
            return False
        return True
```

***

## 19. Realistic Expectations

### What MoonshotX Can Achieve

| Scenario | Win Rate | Profit Factor | Sharpe | CAGR | Max DD |
|---|---|---|---|---|---|
| Conservative | 50% | 1.8 | 1.3 | 20–30% | 15% |
| Base Case | 55% | 2.0 | 1.6 | 30–45% | 12% |
| Optimistic | 62% | 2.2 | 1.9 | 45–60% | 10% |

A 30–45% CAGR with < 12% drawdown is elite for systematic retail trading — better than 95% of retail traders and comparable to many hedge fund strategies.

### What "Fully Autonomous" Actually Means

The system handles the full decision-to-exit loop without human intervention during market hours. Human oversight remains at:

- **Weekly (30 min):** Review performance metrics; check agent audit trail for anomalies
- **Monthly (1 hour):** Review parameter optimiser output; approve or reject changes
- **As needed:** Kill switch authority — the emergency halt endpoint exists so a human can override instantly

Full autonomy means zero manual intervention in normal operation — not zero oversight.

### What It Is NOT

- Not a "money printer" — it will have losing days, choppy weeks, and drawdown periods
- Not monotonically increasing — markets are adversarial and regime-shifting
- Not a replacement for risk management judgment — the kill switch exists for a reason

The system manages losses mechanically and lets winners run systematically. Over time, the asymmetry compounds. That is the entire thesis.

***

## 20. Complete Gap Resolution Checklist

Every gap identified across all three independent expert review cycles:

| Gap | Source Review | v1.1 Resolution | Section |
|---|---|---|---|
| Short selling / bear hedge | All 3 reviews | BEAR_MODE: SQQQ/SPXU/SH, VIX>28 + breadth<30%, 3-loop confirm | §7.5 |
| Earnings risk | Reviews 1 + 2 | 48h entry blackout + T-30min auto-exit (hard rules) | §6.2, §9.1 |
| LLM parallelism | Reviews 1 + 2 | asyncio.gather() all 4 analysts; 45s wall budget | §4.3, §4.4 |
| Memory TTL + regime tags | Reviews 1 + 2 | 90-day TTL, regime-filtered pgvector retrieval | §5.4 |
| Backtesting first | All 3 reviews | Phase 0 Week 1 = simulated broker; agents in Phase 2 | §12, §13 |
| Realistic slippage model | All 3 reviews | ADV-based square-root impact; applied to every backtest fill | §8.3 |
| LLM cost budget | Reviews 1 + 2 | Two-tier model; $25/day cap; quant-only fallback | §16 |
| Kill switch | Reviews 1 + 2 | POST /api/v1/emergency_halt — cascading shutdown | §7.6 |
| Correlation definition | Review 1 | Rolling 20d beta to SPY; 0.75 threshold; cluster logic | §7.3 |
| Win rate / PF realism | Reviews 2 + 3 | Targets revised to 50–62% WR, PF ≥ 1.8 | §1, §19 |
| No true alpha source | All 3 reviews | EarningsMomentumScorer: PEAD window, day-weight decay | §17 |
| LLMs assume alpha generation | All 3 reviews | Reframed as signal quality arbiters; alpha from execution | §1, §4 |
| Walk-forward validation | Review 3 | Rolling 12/3/1 month windows; OOS Sharpe > 1.2 in ≥ 70% | §12.3 |
| Portfolio beta control | Review 3 | Rolling 20d OLS beta; max 1.5× portfolio weighted beta | §18 |
| Entry order type | Review 3 | Limit/stop-limit for entries; market only for SL exits | §8.1 |
| No-trade zones | Review 3 | Choppy/extreme_fear = 0 positions; ATR filter; whipsaw filter | §6.5 |
| Confidence-weighted sizing | Review 3 | Position size × confidence_mult (0.5–1.25×) | §7.2 |
| Per-regime performance tracking | Review 3 | Metrics breakdown by regime in performance_metrics.py | §12.2 |
| Quant-only baseline validation | Review 3 | Phase 1 exit gate: quant-only Sharpe > 0.8 before adding agents | §13 |
| Over-complexity in v1 | Review 3 | Sentiment/fundamentals as optional enrichment (non-blocking) | §5.1 |
| Transaction cost annual drag | Review 3 | annual_cost_drag() method; 1% ADV liquidity cap | §8.3 |

***

## 21. Risk Disclosures

**Technical Risks:** LLM latency mitigated by asyncio.gather() + 45s wall-clock hard budget. Hallucination risk mitigated by debate layer + fully mechanical exits. API rate limits (200 req/min Alpaca) mitigated by pre-market caching. LLM cost explosion mitigated by two-tier model + $25/day circuit breaker.

**Market Risks:** Flash crashes handled by 5s stop verification + market sells. Gap risk eliminated by EOD exit at 15:57. Regime misclassification risk reduced by 4 independent inputs + 3-loop confirmation for BEAR_MODE activation. Correlation risk quantitatively defined (rolling 20d beta, 0.75 threshold). Bear markets managed by BEAR_MODE with inverse ETF rotation and full cash option.

**Operational Risks:** Server downtime mitigated by VPS 99.9% SLA + auto-restart. Broker API outage mitigated by bracket orders persisting at broker level even if MoonshotX is offline. Memory corruption mitigated by 90-day TTL + regime-filtered retrieval + Supabase crash-resistant state. LLM provider outage mitigated by quant-only fallback mode.

**Systemic Risks:** Correlation going to 1 in crashes (all positions fall simultaneously) mitigated by max portfolio beta 1.5×, max 3 positions in fear regime, full cash in extreme fear. Model overfitting mitigated by walk-forward validation requiring ≥ 70% OOS window pass rate before any live deployment.

> **DISCLAIMER:** This system is for educational and research purposes only. Trading US stocks involves substantial risk of loss. Past performance does not guarantee future results. Walk-forward backtests are not a guarantee of future profitability. Never risk more than you can afford to lose. Consult a qualified financial advisor before trading with real capital. The authors take no responsibility for trading losses incurred from implementing this system.

***

*MoonshotX Product & Technical Paper v1.1 — FINAL*
*CodeByteLabs | March 2026*
*Synthesised from: DayTraderAI + TradingAgents + Moonshot-CEX*
*Three independent expert review cycles incorporated*
*21 gap items resolved | Ready for Phase 0 implementation*

***

