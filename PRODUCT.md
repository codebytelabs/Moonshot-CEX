# Moonshot-CEX — Product Document

**Version:** 3.0  
**Updated:** March 2026  
**Stage:** Production — self-hosted autonomous trading system

---

## 1. Vision

> **A swarm of AI agents that never sleeps, never panics, and compounds your capital on Binance and Gate.io around the clock.**

Moonshot-CEX is a fully autonomous, multi-agent crypto trading system for centralized exchanges. It delivers institutional-grade strategy intelligence — Bayesian decision making, conviction-aware sizing, multi-timeframe TA, and adaptive regime management — in a self-hosted, auditable personal bot.

**One goal:** Rapidly grow a CEX spot portfolio with mathematically-grounded, emotion-free, 24/7 autonomous execution.

---

## 2. Problem

Manual crypto trading on CEX fails because:

| Failure Mode | Root Cause |
|---|---|
| Emotional decisions | FOMO entries, panic exits, revenge trades |
| Missed opportunities | 24/7 markets need 24/7 presence |
| Inconsistent sizing | No mathematical framework, gut-feel sizing |
| Strategy drift | Risk appetite changes under market stress |
| Capital laziness | Funds sit idle; no dynamic reallocation |

Existing solutions fall short:

- **3Commas / Pionex** — black-box, no AI decision layer, no Bayesian inference
- **Simple grid/DCA bots** — no intelligence, no stop management, blow up in trends
- **Freqtrade / custom bots** — research-grade, not production-autonomous; no LLM layer

---

## 3. Solution

Moonshot-CEX is a **10-agent autonomous swarm** that handles the full trading lifecycle:

| Layer | Agent | What It Does |
|---|---|---|
| **Scan** | WatcherAgent | Scans 150+ USDT pairs every 30s; ranks by volume + momentum |
| **Analyze** | AnalyzerAgent | Deep 4-TF TA (5m/15m/1h/4h) — RSI, MACD, EMA, ATR, OBV; produces ta_score 0–100 |
| **Enrich** | ContextAgent | LLM (Perplexity/OpenRouter) sentiment, catalysts, and risks per token |
| **Decide** | BayesianEngine | Calibrated posterior probability; online prior learning; 0.65/0.75/0.85 mode thresholds |
| **Size** | RiskManager | Conviction-aware Half-Kelly × liquidity gate × TA quality — no two trades are sized the same |
| **Execute** | ExecutionCore | CCXT market buy entry; limit-first exit with automatic repricing |
| **Protect** | PositionManager | Tiered exits (2R/5R), trailing stop, pyramid adds, momentum-loss cuts, 24h time exit |
| **Adapt** | QuantMutator | Self-tunes Bayesian threshold from rolling win rate and PnL feedback |
| **Supervise** | BigBrother | Regime detection (bull/sideways/bear); mode management; anomaly alerts |
| **Interface** | TinyOffice | Natural language chat: "Why did you buy SOL?" gets a coherent answer |

---

## 4. Target Users

| User Type | Account Size | Use Case |
|---|---|---|
| Solo quant traders | $500 – $50K | Fully autonomous CEX portfolio growth |
| Passive income builders | $1K – $100K | 24/7 bot with hard risk controls, not a casino |
| ML/algo hobbyists | Any | Production Bayesian + Kelly system without a PhD |

---

## 5. Key Features

### 5.1 Exchange-First Data Architecture _(v3.0)_

All financial metrics are sourced **directly from the exchange** — not from databases or hardcoded values:

- **Equity**: Fetched live from Gate.io at startup; bot refuses to trade until confirmed. No `INITIAL_EQUITY_USD` hardcoding — works with any account size ($100 or $100K)
- **PnL**: FIFO cost-basis computation from raw exchange fills — not estimated, not hardcoded
- **Positions**: Real-time unrealized PnL per position from live price feeds
- **Trade history**: Complete fill-by-fill history with correct realized PnL

### 5.2 Conviction-Aware Position Sizing _(v3.0)_

The biggest v3.0 improvement. No two trades are sized the same:

```
Position Size = Kelly_base × Conviction × Liquidity × TA_Quality
```

| Factor | Range | Driven By |
|---|---|---|
| **Conviction** | 0.55× → 1.45× | Bayesian posterior vs threshold |
| **Liquidity** | 0.45× → 1.00× | 24h trading volume in USD |
| **TA Quality** | 0.90× → 1.10× | Composite ta_score (0–100) |

**Example impact:**  
A *breakout* on BTC/USDT with `posterior=0.92`, `vol_usd=$250M`, `ta_score=82` → **1.43×** base size.  
A borderline *neutral* on an illiquid altcoin → **0.26×** base size.  
The 15% single-exposure hard cap always holds regardless.

### 5.3 Calibrated Bayesian Decision Engine _(v3.0)_

- Replaced arbitrary normalisation factor with **mathematically correct Bayes theorem**
- `mean_reversion` prior lowered (0.52 → 0.38): contrarian setups now require very strong evidence to pass the 0.65 threshold — correctly filtered in a momentum system
- **Online learning**: Setup-type priors update (α=0.05) after each closed trade
- Mode-adaptive thresholds: `normal=0.65` → `volatile=0.75` → `safety=0.85`

### 5.4 Multi-Setup Technical Analysis

5 setup types detected across 4 timeframes (weighted 20/30/30/20):

| Setup | Prior | When |
|---|---|---|
| `breakout` | 0.62 | RSI spike + EMA aligned + volume surge on 4h+ |
| `momentum` | 0.58 | RSI 50–70 + MACD positive + OBV accumulation |
| `pullback` | 0.55 | Higher-TF bullish, lower-TF RSI dip to support |
| `consolidation_breakout` | 0.60 | Tight Bollinger bands + volume expansion |
| `mean_reversion` | 0.38 | Oversold + BB touch — highly selective filter |

### 5.5 Three-Tier Exit System

Capital is never locked in a single all-or-nothing exit:

| Tier | Trigger | Action |
|---|---|---|
| **Tier 1** | R-multiple ≥ 2× | Sell 25% — lock partial profit, trail tightens |
| **Tier 2** | R-multiple ≥ 5× | Sell another 25% — capture the extended move |
| **Runner** | Trailing stop | Remaining 50% rides with a trailing stop to capture moonshots |

Early exits for dead positions: momentum-loss detection at 15m / 30m / 45m intervals.  
Pyramid adds available for positions ≥ 1.5R after Tier 1.

### 5.6 Adaptive Regime Management

BigBrother continuously monitors the macro market state:

| Regime | Detected When | Strategy Adjustments |
|---|---|---|
| **Bull** | BTC +3%+, high volume, win rate > 55% | Wider stops, higher TPs, longer holds (5h) |
| **Sideways** | Neutral BTC, mixed signals | Default parameters |
| **Bear** | BTC −3%+, fear volume, win rate < 40% | Tight stops, quick exits (1.5h), safety mode |

Quant Mutator tightens/loosens Bayesian thresholds based on rolling win rate and daily PnL.

### 5.7 Multi-Exchange Support

- **Gate.io** (primary — production + testnet)
- **Binance** (production + demo API)
- **KuCoin** (production)

Hot-swappable via `.env`. CCXT async connector with rate limiting, precision rounding, and retry backoff.

### 5.8 Real-Time Dashboard + AI Chat

- **Dashboard** (port 3001): Live positions, unrealized PnL, equity chart, agent feed, Bayesian decisions, regime status
- **TinyOffice** (port 3000): Natural language interface — ask "What's my win rate?", "Why did you buy ETH?", "Pause trading"
- **WebSocket**: Dashboard updates pushed every 30s cycle
- **Emergency stop**: Single button closes all open positions immediately

### 5.9 Paper → Demo → Live Safety Ladder

Every deployment starts safe:

1. `EXCHANGE_MODE=paper` — full simulation, no API calls, no risk
2. `EXCHANGE_MODE=demo` — real orders on exchange sandbox
3. `EXCHANGE_MODE=live` — production capital

---

## 6. Performance Expectations

| Mode | Expected Annual Return | Max Drawdown | Win Rate Target |
|---|---|---|---|
| Conservative (safety mode) | 15–30% | < 10% | > 55% |
| Balanced (normal mode) | 40–80% | < 15% | > 50% |
| Aggressive (bull regime) | 80–200% | < 20% | > 45% |

> ⚠️ Past performance does not guarantee future results. Always start in paper/demo mode. Crypto markets are highly volatile.

---

## 7. Current Improvements — Business Impact

The following improvements were implemented in v3.0. Each has a measurable expected impact on portfolio performance:

| Improvement | Implementation | Expected Impact |
|---|---|---|
| **Exchange-first equity** | Startup retries exchange 5× before swarm starts | Eliminates trades with incorrect equity — prevents misized positions |
| **FIFO realized PnL** | Fill-by-fill cost matching | Accurate trade analysis; correct decision feedback to Kelly + priors |
| **Conviction sizing** | Posterior × liquidity × TA multipliers on base size | High-conviction trades get up to 1.45× capital → better risk-adjusted returns |
| **Bayesian formula fix** | Replaced ×6.5 with correct Bayes theorem | Calibrated posteriors → sizing multiplier acts on accurate confidence signals |
| **mean_reversion prior** | 0.52 → 0.38 | Filters contrarian setups in momentum context → fewer conflicting trades |
| **Capital deployment** | Portfolio exposure raised to 95% | Reduces idle capital drag on portfolio NAV to virtually 0% |
| **Aggressive Trade Frequency** | Lowered Analyzer/Mutator score ceilings and Bayesian thresholds | Maximizes trading velocity to ride micro-momentum waves in under-utilized markets |
| **Early Pyramiding** | Fixed entry conditions to allow compounding at 1.5R (before Tier 1) | Increases size automatically on winning bets before taking profits |
| **UI Ghost Fixes & NAV Charting** | <$3 dust filtering + MongoDB historical snapshots | Accurate, clutter-free exchange snapshotting with 1H/1D/7D equity charting |

---

## 8. Future Roadmap

Improvements validated by 2024–2025 algo trading research, ordered by expected impact:

| Priority | Enhancement | Expected Impact | Complexity |
|---|---|---|---|
| 🔴 High | **Volatility-parity sizing** — size inversely proportional to realized ATR per coin | Equalizes risk contribution across coins; improves Sharpe | Medium |
| 🔴 High | **LSTM/Transformer price forecaster** — additional filter agent for 15m–1h predictions | +12.8% ROI per 2025 multi-agent studies | High |
| 🟠 Medium | **On-chain metrics fusion** — active addresses, transaction volume into Bayesian priors | +15–30% signal accuracy on momentum setups | Medium |
| 🟠 Medium | **Dynamic time exit by regime** — 48h in bull, 12h in sideways, 8h in bear | Reduces opportunity cost in strong trends | Low |
| 🟡 Low | **Better support/resistance** — pivot clustering vs naive min/max | More accurate entry zones and stop placement | Medium |
| 🟡 Low | **TWAP order splitting** — slice large entries over 2–3 ticks | −20% slippage on positions > 5% equity | Medium |
| 🟡 Low | **Market-cap tiering** — small-cap gets lower single exposure cap | Protects against low-liquidity blow-ups | Low |

---

## 9. Competitive Analysis

| Feature | Moonshot-CEX | 3Commas/Pionex | Freqtrade | Manual |
|---|---|---|---|---|
| Multi-agent AI swarm | ✅ | ❌ | ❌ | ❌ |
| Conviction-scaled sizing | ✅ | ❌ | ❌ | ❌ |
| Calibrated Bayesian decisions | ✅ | ❌ | ❌ | ❌ |
| Exchange-first data (no hardcoding) | ✅ | ✅ | ✅ | ✅ |
| LLM market context enrichment | ✅ | ❌ | ❌ | ❌ |
| Online prior learning | ✅ | ❌ | ❌ | ❌ |
| Regime-adaptive parameters | ✅ | ❌ | Limited | ❌ |
| Natural language chat interface | ✅ | ❌ | ❌ | ✅ |
| Paper / Demo / Live modes | ✅ | ✅ | ✅ | ❌ |
| Self-hosted + fully auditable | ✅ | ❌ | ✅ | ✅ |
| Prometheus observability | ✅ | ❌ | ✅ | ❌ |

---

## 10. User Journey

1. **Setup (10 min):** Clone → copy `.env.example` → add API keys
2. **Paper test (1–7 days):** Validate strategy with zero risk
3. **Demo test (3–7 days):** Real exchange sandbox — verify fills and sizing
4. **Go live:** Flip `EXCHANGE_MODE=live` — system trades autonomously 24/7
5. **Monitor:** Dashboard + Telegram/Discord alerts provide visibility without requiring attention

---

## 11. Safety Philosophy

| Principle | Implementation |
|---|---|
| **Never blow up the account** | Daily loss limit, max drawdown circuit breaker, consecutive loss pause |
| **Never trade blind** | Equity fetched from exchange before every session; trades blocked if equity unknown |
| **Never over-size** | Kelly fraction capped; liquidity gate prevents over-sizing illiquid coins |
| **Always auditable** | Every decision logged with full posterior, TA score, sentiment, and regime state |
| **Always stoppable** | Emergency stop via dashboard or CLI closes all open positions in seconds |
| **Spot only** | No margin, no futures, no leverage — cannot exceed 100% equity exposure |
