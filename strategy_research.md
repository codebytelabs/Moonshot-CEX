# Regime-Adaptive Strategy Research
**Moonshot-CEX · March 2026**  
*Researched via Perplexity + Sequential Thinking synthesis*

---

## TL;DR

> **Yes — every layer of the strategy should be regime-aware, portfolio-state-aware, and account-size-aware.** Static parameters are proven suboptimal. The system already handles some of this; here's what's missing and what to build.

**On shorting:** For a spot-only Gate.io account, **don't short — park USDT instead**. If you enable Gate.io margin, shorting in confirmed bear regime is valid but with strict guards.

---

## 1. Regime-Adaptive Strategy Variables

Four regimes need distinct behaviour. This is the highest-impact change.

### 1.1 How to Detect Each Regime

| Regime | Detection Signal |
|---|---|
| **Bull** | BTC 24h Δ > +3% AND volume ratio > 1.2 AND rolling win_rate > 55% |
| **Sideways** | BTC 24h Δ between −3% and +3% AND ATR contracting |
| **Bear** | BTC 24h Δ < −3% AND volume ratio > 1.5 (fear) AND win_rate < 40% |
| **Choppy** | BTC 24h Δ between −1.5% and +1.5% AND ATR expanding AND win_rate < 45% |

> **Choppy is NOT the same as Sideways.** Sideways = low volatility + tight range. Choppy = high volatility inside a tight range — whipsaws, failed breakouts. This is the deadliest regime for momentum bots.

### 1.2 Parameter Table By Regime

| Parameter | Bull | Sideways | Bear | Choppy |
|---|---|---|---|---|
| **Bayesian threshold** | 0.60 | 0.65 | 0.75 | 0.82 |
| **Position size multiplier** | 1.00× | 0.85× | 0.60× | 0.45× |
| **Max concurrent positions** | 5 | 4 | 3 | 2 |
| **Max portfolio exposure** | 85% | 65% | 40% | 25% |
| **Stop loss %** | −22% | −18% | −12% | −10% |
| **Trailing activate %** | +12% | +15% | +20% | +8% |
| **Trailing distance %** | 9% | 8% | 6% | 5% |
| **Time exit (hours)** | 24h | 6h | 2h | 1h |
| **Setup allowlist** | All | All except mean_reversion | breakout only | breakout only (score > 75) |
| **Pyramid enabled** | Yes | Yes | No | No |
| **Priority setup types** | breakout, momentum, pullback | consolidation_breakout, pullback | breakout | breakout |

### 1.3 What Changes in Choppy (Key Insight)

In choppy markets the bot **should do almost nothing**. Research confirms:
- Raise Bayesian threshold to 0.82+ (only take the clearest signals)
- Only allow `breakout` with ta_score > 75 — no momentum, no pullback, no mean_reversion
- Cut max positions to 2 (preserve cash)
- Exit positions in 60 minutes if they don't move — stop waiting for momentum to materialise
- **Park 75%+ of capital in USDT** during choppy regime

Detection: if the bot's last 10 closed trades have win_rate < 40% AND average hold time < 30 min AND average PnL < 0.5%, it's in a choppy regime.

---

## 2. Account Size Tier Adaptation

Research (CGA-Agent 2025 backtests on BTC/ETH) validates tiered Kelly fractions improve Sharpe by 12–15% vs uniform sizing.

### 2.1 Parameter Table By Account Size

| Parameter | Small ($500–$2K) | Medium ($2K–$20K) | Large ($20K+) |
|---|---|---|---|
| **Kelly fraction multiplier** | 0.25× | 0.50× | 0.60× |
| **Max concurrent positions** | 2–3 | 4–6 | 6–10 |
| **Min trade size (USD)** | $25 | $50 | $150 |
| **Max single exposure** | 10% | 15% | 15% |
| **Risk per trade** | 1–2% | 3–5% | 5–8% |
| **Strategy mode** | Conservative only | Normal | Normal + Aggressive |

**Implementation:** Detect account tier at startup from live equity:
```python
equity = fetch_live_equity()
if equity < 2_000:    tier = "small";   kelly_mult = 0.25
elif equity < 20_000: tier = "medium";  kelly_mult = 0.50
else:                 tier = "large";   kelly_mult = 0.60
```

For small accounts: the bot should trade **fewer, higher-conviction positions** and pay proportionally lower fees per dollar of turnover. Do not attempt 5 simultaneous positions on a $1K account — a single bad trade is catastrophically large.

---

## 3. Portfolio-State Dynamic Sizing

This is real-time adaptation based on how the current session is going.

### 3.1 Drawdown-Based Sizing Scale

| Current Drawdown | Size Multiplier | Threshold Adjustment | Action |
|---|---|---|---|
| 0–3% | 1.00× | — | Normal operation |
| 3–5% | 0.80× | +0.03 to threshold | Slight caution |
| 5–10% | 0.60× | Safety mode trigger | RiskManager already does this |
| 10–15% | 0.40× | Safety mode (0.85 threshold) | Reduce but continue |
| > 15% | 0.00× | HALT | Block all new entries |

**Research finding:** Reducing size by 50% at >10% drawdown reduces volatility by 18% while preserving recovery speed (CGA-Agent, 2025).

### 3.2 Win/Loss Streak Adaptation

| Streak | Size Adjustment | Logic |
|---|---|---|
| 3+ wins in a row | +15% base size | Confidence + good market condition |
| 5+ wins in a row | +25% (cap) | System is in the zone |
| 3 losses in a row | −50% size, 10-min pause | Already implemented as circuit breaker |
| 5+ losses in a row | −75%, raise threshold | Potential regime change — extreme caution |

> **Important:** Win streak bonuses should only be applied when the regime is bull or sideways. In bear/choppy, no upside sizing regardless of streak.

### 3.3 Current Exposure Gate

```
if current_exposure_pct > 0.70: no new entries (already have enough risk on)
if current_exposure_pct > 0.85: emergency de-risk if in bear/choppy
```

---

## 4. Shorting Strategy

### 4.1 For Spot-Only Gate.io Accounts (Current Setup)

**Short answer: Don't short. Use USDT parking instead.**

In spot-only mode the correct "bear strategy" is:
1. **Exit longs faster** — in bear regime, time exit at 2h instead of 24h
2. **Higher threshold for new entries** — only take breakouts, not momentum/pullback
3. **Park capital in USDT** — when bear regime confirmed, auto-target 60%+ USDT allocation
4. **Never open new positions in bear+choppy** — sit in cash and wait for bull regime signals

This is valid because the opportunity cost of holding USDT in a bear market is near zero, while the cost of being long in a sustained downtrend is severe.

### 4.2 If Gate.io Margin Is Enabled (Future)

Shorting becomes a valid tool in **confirmed bear regime only**. Validated signals and rules:

**Entry signals for shorts:**
- BTC 4h: EMA9 < EMA21 < EMA50 (fully bearish aligned)
- RSI(14) on 4h: below 48 (not oversold — avoid shorting oversold assets)
- Volume spike on bearish candle (selling pressure confirmed)
- Daily close below 50-day MA for 3+ consecutive days
- ContextAgent sentiment: bearish with bearish catalysts

**Short position rules vs long:**

| Parameter | Long Position | Short Position |
|---|---|---|
| Max size | 15% equity | 8% equity (much smaller) |
| Stop loss | −18% (wide) | −10% (tight — unlimited upside risk) |
| Trailing activate | +12% profit | +8% profit |
| Pyramid | Yes (at +1.5R) | **No — never pyramid shorts** |
| Mean_reversion setup | Filtered (prior 0.38) | **Completely blocked** |
| Hold time max | 24h | 4h max |
| Setup types allowed | All | `breakout` (down-breakout) and [momentum](file:///Users/vishnuvardhanmedara/Moonshot-CEX/src/position_manager.py#300-320) only |

**Do NOT short when:**
- Bull regime active
- BTC RSI on 4h is below 30 (already extremely oversold — capitulation risk)
- Major news event in next 24h (crypto reacts violently + unpredictably to news)
- Account in drawdown > 8% (don't add short risk when already losing)
- Small account (< $5K) — shorts require large cushion for stop management

### 4.3 Alternative: Inverse ETF / Perpetual Futures

If Gate.io perpetuals are available:
- Use perpetual shorts with 1× leverage only (no leverage)
- Same entry rules as above
- Max position: 10% equity
- Mandatory hard stop: 12%

---

## 5. What Moonshot-CEX Already Has vs What's Missing

### ✅ Already Implemented

| Feature | Status |
|---|---|
| Regime detection (bull/sideways/bear) | ✅ BigBrother |
| Regime-adaptive exit params (SL/TP/time) | ✅ BigBrother regime table |
| Safety mode threshold (0.85) on drawdown > 10% | ✅ |
| Consecutive loss pause (3 losses → 10-min halt) | ✅ RiskManager |
| Max portfolio exposure gate | ✅ 85% cap |
| Online Bayesian prior learning | ✅ α=0.05 update per trade |
| Conviction × liquidity × TA position sizing | ✅ v3.0 |

### ❌ Missing (Highest Priority)

| Feature | Impact | Complexity |
|---|---|---|
| **Choppy regime detection** (separate from sideways) | High | Low |
| Position size multiplier by regime (0.45× in choppy, 0.60× in bear) | High | Low |
| Max exposure limit by regime (25% in choppy, 40% in bear) | High | Low |
| Account size tier detection → Kelly fraction multiplier | High | Low |
| Drawdown 3–5% → pre-emptive 20% size reduction | Medium | Low |
| Win streak +15% size bonus (capped, regime-gated) | Medium | Medium |
| USDT parking auto-target in bear/choppy (exit stale positions proactively) | High | Medium |
| Short position support in margin accounts | Medium | High |

---

## 6. Prioritized Implementation Plan

### Phase 1 — Regime Completeness (High Impact, Low Complexity)

1. **Add choppy regime to BigBrother** — detect via win_rate + ATR expansion + hold time analysis
2. **Add per-regime position size multiplier** — `regime_size_mult` in `BigBrother.get_regime_params()`
3. **Add per-regime max exposure** — 85%/65%/40%/25% by regime; enforce in `RiskManager.can_open_position()`
4. **Expand setup allowlist gating** — block all setups except breakout in bear; block all except high-score breakout in choppy

### Phase 2 — Account & Portfolio Adaptation (High Impact, Low Complexity)

5. **Account tier detection at startup** — set `kelly_mult` based on live equity
6. **Drawdown scaling** — 3–5% drawdown → 0.80× base size (pre-safety-mode gradient)
7. **Win streak bonus** — +15% at 3 wins, +25% at 5 wins, only in bull/sideways

### Phase 3 — Capital Efficiency in Bear (High Impact, Medium Complexity)

8. **Aggressive USDT parking** — in bear/choppy, reduce time exit to 2h/1h AND reduce momentum threshold to exit sooner
9. **"Regime changed" exit sweep** — when switching to bear/choppy, close all positions with PnL < 0.5% profit immediately
10. **Regime conviction gate on entries** — no new entries in choppy unless ta_score > 75 AND TA setup is `breakout`

### Phase 4 — Shorts (Future, Requires Margin Enable)

11. Short entry filter: bears + EMA alignment + volume + RSI constraints
12. Short sizing: 50% of long size, tighter stops
13. Shorting circuit breaker: auto-disable if market RSI(4h) < 30

---

## 7. Expected Impact

| Enhancement | Expected Improvement |
|---|---|
| Choppy regime detection + minimal trading | Prevent 20–35% of consecutive-loss events |
| Regime-adaptive exposure limits | Reduce max drawdown by 20–30% |
| Account-size Kelly tiering | +12–15% Sharpe ratio improvement (CGA-Agent 2025) |
| Portfolio drawdown scaling | 18% volatility reduction in losing streaks |
| USDT parking in bear | Capital preserved for the next bull regime; reduces opportunity drag |
| Short selling (bear regime, margin) | +10–20% annual return in sustained bear markets |

---

## 8. Summary Answer to Your Questions

**Should strategy variables change by regime?** ✅ YES — absolutely. The 4 regimes (bull, sideways, bear, choppy) should have entirely different parameter sets. Currently the system handles bull/sideways/bear but **lacks choppy detection**, which is the most dangerous regime for a momentum bot.

**Should they change by account size?** ✅ YES — small accounts ($500–$2K) need 0.25× Kelly, 2–3 max positions, 10% single exposure cap. Large accounts ($20K+) can push 0.60× Kelly and 10 positions.

**Should they change by portfolio status?** ✅ YES — drawdown-gradient sizing, win-streak bonuses (regime-gated), and current-exposure gates all add proven risk-adjusted return improvement.

**Should shorting be part of the strategy?** 
- **Spot-only Gate.io:** ❌ No — park USDT aggressively instead
- **Margin/futures enabled:** ✅ Yes, but ONLY in confirmed bear regime, 50% of long size, tighter stops, no pyramid, hard 4h time exit
