# MoonshotX: Autonomous Multi-Agent US Stock Trading System

## Product & Technical Paper v1.0

**Author:** CodeByteLabs | **Date:** March 2026 | **Status:** Design Phase

---

## 1. Executive Summary

**MoonshotX** synthesizes three battle-tested codebases into a fully autonomous US stock trading system:

| Source Repo | Contribution | Key Innovation |
|---|---|---|
| **DayTraderAI** | Alpaca execution, 50+ indicators, R-multiple tracking, Wave Rider | US stock infrastructure |
| **TradingAgents** | LangGraph multi-agent brain, analyst debates, reflection/memory | LLM-powered decision intelligence |
| **Moonshot-CEX** | Trailing stops, Bayesian engine, regime detection, adaptive thresholds | Battle-tested position management |

### Core Thesis

> **LLM agents decide *what* and *when* to buy. Mechanical quant systems decide *when* to sell. Never the reverse.**

### Target Performance

| Metric | Target | Rationale |
|---|---|---|
| Win Rate | 60-70% | Multi-agent consensus filters low-quality entries |
| Profit Factor | ≥ 2.5 | Trailing stops let winners run; hard SL caps losers |
| Sharpe Ratio | ≥ 2.0 | Regime-adaptive sizing reduces volatility drag |
| Max Drawdown | < 10% | 5-tier risk hierarchy with circuit breakers |
| Daily Return | 0.3-0.7% | Compounding: $50K → $125K-$250K/year |

### Key Differentiators

1. **Closed-loop autonomy**: Agents decide → execute → manage → reflect → improve
2. **Debate-driven consensus**: Bull/Bear + Aggressive/Conservative argue before every trade
3. **Mechanical exits**: No LLM hallucination risk on position management
4. **Self-improving memory**: Every trade outcome feeds back into agent memory

---

## 2. Problem Statement

| Problem | Evidence | MoonshotX Solution |
|---|---|---|
| Single-brain decisions | EMA crossover alone = noise | 4 analyst agents + debate teams |
| LLMs managing positions | Non-deterministic, hallucinate | LLMs for entries ONLY, mechanical exits |
| No learning from mistakes | DayTraderAI repeated errors | TradingAgents reflection system |
| Over-trading | Moonshot-CEX: 185 trades/day = loss | Max 5 positions, Bayesian ≥ 0.45 |
| Premature exits | Winners held 0.41h vs losers 3.78h | Trailing stop primary, time exit only for losers |

---

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
| Strategy Engine | `backend/trading/strategy.py` | ⚠️ Partial — extract signals |

**Key lessons:** Bracket orders essential, 5s stop verification catches failures, R-multiple thinking normalizes risk, EOD exit at 15:57 prevents gap risk, no entries after 15:30.

### 3.2 From TradingAgents

| Component | File | Repurpose? |
|---|---|---|
| TradingAgentsGraph | `graph/trading_graph.py` | ✅ Core — adapt for real-time |
| Graph Setup (LangGraph) | `graph/setup.py` | ✅ Core |
| Reflection System | `graph/reflection.py` | ✅ Core — key innovation |
| Signal Processing | `graph/signal_processing.py` | ✅ Core |
| 4 Analyst Agents | `agents/analysts/*.py` | ✅ Core |
| Bull/Bear Researchers | `agents/researchers/*.py` | ✅ Core — debate system |
| Research Manager | `agents/managers/research_manager.py` | ✅ Core |
| Portfolio Manager | `agents/managers/portfolio_manager.py` | ✅ Core |
| 3 Risk Debators | `agents/risk_mgmt/*.py` | ✅ Core |
| FinancialSituationMemory | `agents/utils/memory.py` | ✅ Core — learning |
| Data Interface | `dataflows/interface.py` | ✅ Core |

**Key lessons:** Debate prevents confirmation bias, reflection is the learning engine, deep-think LLMs for complex reasoning + quick-think for routine. **Critical gap: NO execution engine** — MoonshotX fills this.

### 3.3 From Moonshot-CEX (Lessons Paid in Real Dollars)

| Component | Repurpose? | Key Lesson |
|---|---|---|
| Bayesian Decision Engine | ✅ Core | Entry quality gate, posterior ≥ 0.45 |
| QuantMutator | ✅ Core | Hard floor 0.40, ceiling 0.55 |
| BigBrother Regime | ✅ Core | Regime-specific parameter scaling |
| Position Manager exits | ✅ Core | Trailing stop = THE profit engine |
| Execution Core | ✅ Core | Market sells for SL (IOC failed: -$747) |
| Risk Manager | ✅ Core | Drawdown tracking, position limits |

**Critical lessons:** Threshold floor 0.12 destroyed us (-$387/day), 185 trades/day = guaranteed loss, premature exits killed 100% of winners, time-exit only for losers, 4h symbol cooldown prevents churn, dust positions cycle forever without cleanup.

---

## 4. System Architecture

### 4.1 Data Flow — One Complete Cycle

```
1. SCAN     → Universe scanner: top 50 liquid stocks
2. DATA     → Feature engine: 50+ indicators per stock
3. ANALYZE  → 4 analyst agents produce reports (parallel)
4. DEBATE   → Bull/Bear researchers argue N rounds
5. JUDGE    → Research Manager synthesizes verdict
6. PLAN     → Trader agent creates entry plan
7. RISK     → 3-way risk debate evaluates plan
8. APPROVE  → Portfolio Manager approves/rejects
9. GATE     → Bayesian Engine: posterior ≥ 0.45
10. EXECUTE → Smart Order Executor: bracket order via Alpaca
11. MANAGE  → Position Manager: trailing, R-multiples, time exit
12. EXIT    → Mechanical triggers (SL/trailing/time/EOD)
13. REFLECT → All agents review outcome, update memory
14. ADAPT   → QuantMutator adjusts, optimizer tunes
15. REPEAT  → Loop every 60s during market hours
```

### 4.2 Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Agent Framework | LangGraph + LangChain |
| LLM Providers | OpenAI GPT-5.x (primary), Claude (backup) |
| Broker API | Alpaca Markets (commission-free, brackets) |
| Backend | FastAPI + uvicorn |
| Database | Supabase (PostgreSQL) |
| Frontend | React 18 + TypeScript + Tailwind |
| Data | yFinance + Alpaca WS + Twelve Data |
| Deployment | VPS (Chicago proximity) |

### 4.3 Real-Time Loop (Key Adaptation)

TradingAgents is one-shot: `ta.propagate("NVDA", "2024-05-10")`. MoonshotX runs continuously:

```python
async def trading_loop():
    while market_is_open():
        candidates = universe_scanner.get_top_candidates(n=10)
        for ticker in candidates:
            # Fast pre-filter (< 100ms) — avoid expensive LLM pipeline
            if bayesian_engine.quick_score(ticker) < 0.45:
                continue
            # Full agent pipeline (10-30s) — only for promising setups
            state, decision = agents.propagate(ticker, today)
            if decision == "BUY" and portfolio_manager.approved:
                await execution_engine.enter(ticker, decision.plan)
        # Manage existing positions every tick
        await position_manager.tick_all_positions()
        if risk_manager.daily_loss_exceeded():
            break
        await asyncio.sleep(60)
```
