

---

# DEEP ANALYSIS: Why the Bot Went From Printer to Drain

## 76-Trade Data Summary

| Metric | Value |
|--------|-------|
| Total trades | 76 |
| Win rate | **21%** (16W / 58L / 2BE) |
| Total PnL | **-$1,374** |
| Avg win | $47.94 |
| Avg loss | -$36.91 |
| Max win | $339.45 (CTSI, trailing_stop, +6.6%) |
| Max loss | -$186.79 (PTB, stop_loss, -4.0%) |
| Avg hold (wins) | 0.68h |
| Avg hold (losses) | 0.20h |

---

## The Money-Printing Period vs The Bleeding

| | **Trades 1-4 (PRINTER)** | **Trades 5-76 (BLEEDER)** |
|--|---|---|
| PnL | **+$421** | **-$1,795** |
| Win rate | 50% | 19% |
| Avg win | **$212** | $24 |
| Avg loss | $3 | $38 |
| Avg margin/position | **$467** | $223 → $65 |
| Exit mechanism | ALL trailing_stop | 43% early_thesis_invalid |
| Regime | N/A (trending market) | 65% choppy |

**The printer worked because:** Big positions ($467), patient exits (trailing stop only), wins were 64x the losses ($212 vs $3).

**It broke because:** Positions got tiny ($65-88), early_thesis kills 41% of trades before trailing activates, and the regime feedback loop locks everything into choppy.

---

## Exit Reason P&L Breakdown

| Exit Reason | Count | Total PnL | Win Rate | Verdict |
|---|---|---|---|---|
| **early_thesis_invalid** | **31** | **-$863** | **0%** | **#1 KILLER — never wins** |
| stop_loss (all types) | 9 | -$680 | 0% | Normal, expected |
| rotated_out | 6 | -$237 | 0% | Fixed in v4.2 |
| ghost_close_sync | 4 | -$183 | 25% | Exchange sync issue |
| trailing_stop | 3 | +$10 | 67% | Works |
| **trailing_stop_force_ghost** | **23** | **+$578** | **57%** | **THE MONEY MAKER** |

**`early_thesis_invalid` is responsible for 63% of all losses.** It kills positions after just 5 minutes if they're down >1% and never went above +0.3%. In choppy markets with 6-7x leverage, that's basically every trade — spread + slippage alone is often 0.5%.

---

## Complete Variable Table

### Entry Gates

| Variable | Current Value | Range | Impact | Problem? |
|---|---|---|---|---|
| `ANALYZER_MIN_SCORE` | 35 | 20-80 | Minimum TA score to consider entry | OK |
| `CHOPPY_MIN_TA_SCORE` | **50** | 30-80 | Min TA score in choppy/bear regime | **Blocks 90%+ of candidates** |
| `BAYESIAN_THRESHOLD_NORMAL` | 0.40 | 0.10-0.70 | Posterior threshold for entry | OK |
| `REGIME_BAYESIAN_THRESHOLD[choppy]` | **0.55** | 0.40-0.70 | Raised bar in choppy regime | Stacks on top of TA gate |
| `REGIME_SETUP_ALLOWLIST[choppy]` | momentum, momentum_short | varies | Only these setups allowed | OK |
| BTC trend gate | EMA9 >= EMA21×0.997, RSI>40 | - | Blocks longs when BTC weak | OK concept |
| Anti-chase pullback | price < 3% below 1h high | 1-5% | Block exhausted pumps | OK |

### Position Sizing (THE CRITICAL SECTION)

| Variable | Current Value | Effective in Choppy+Volatile | Range | Impact | Problem? |
|---|---|---|---|---|---|
| `MAX_RISK_PER_TRADE_PCT` | 0.08 (8%) | 8% | 2-15% | Base position margin cap | OK |
| `REGIME_CAPITAL[choppy].size_mult` | **0.55** | - | 0.3-1.0 | Regime scaling | **Halves position size** |
| `VOLATILE_MODE_OVERLAY.size_mult` | **0.80** | - | 0.5-1.0 | Stacks on regime | **Double-dips** |
| **Net size multiplier (choppy+volatile)** | - | **0.44×** | - | 0.55 × 0.80 | **Positions crushed to 44%** |
| `REGIME_CAPITAL[choppy].max_single_pct` | **0.08** | 8% | 5-20% | Per-position cap | Only $65-88 margin |
| Drawdown scaling in risk_manager | dynamic | further reduces | - | Compounds the shrinkage | **Triple-dip** |
| `KELLY_FRACTION` | 0.80 | 0.80 | 0.25-1.0 | Kelly criterion fraction | Aggressive but OK |
| `MAX_KELLY_FRACTION` | 0.12 | 0.12 | 0.05-0.20 | Kelly ceiling | OK |

### Exit Rules

| Variable | Base Value | Choppy Effective | Range | Impact | Problem? |
|---|---|---|---|---|---|
| `STOP_LOSS_PCT` | -3.5% | **-2.28%** (×0.65) | -2% to -5% | Hard loss floor | **Too tight at -2.28% with 7x lev** |
| `TRAILING_STOP_ACTIVATE_PCT` | 1.0% | **0.7%** (×0.7) | 0.5-3.0% | When trailing activates | Borderline OK |
| `TRAILING_STOP_DISTANCE_PCT` | 1.0% | **0.7%** (×0.7) | 0.5-2.0% | Trailing distance | OK |
| `TIME_EXIT_HOURS` | 3.0h | **2.25h** (×0.75) | 1-6h | Kill stale losers | OK |
| **`early_thesis_invalid`** | 5min, pnl<-1%, peak<0.3% | same | - | Kill positions that never validated | **0% WR, -$863, KILLS EVERYTHING** |
| `momentum_faded` | 30min, peak>=3%, giveback>=60% | same | - | Protect big peaks from reversal | OK, rarely triggers |

### Leverage & Risk

| Variable | Current Value | Range | Impact | Problem? |
|---|---|---|---|---|
| `FUTURES_DEFAULT_LEVERAGE` | 7 | 1-10 | Base leverage | OK but amplifies noise |
| `FUTURES_MAX_LEVERAGE` | 10 | 5-20 | Ceiling | OK |
| `MAX_DRAWDOWN_PCT` | 0.25 (25%) | 0.10-0.50 | Safety drawdown trigger | OK |
| `CIRCUIT_BREAKER_PCT` | 0.08 (8%) | 0.03-0.15 | Emergency close trigger | OK for leverage |

### Regime Detection (THE FEEDBACK LOOP)

| Signal | Weight | Current | Problem? |
|---|---|---|---|
| BTC 24h change | **4×** | btc_change/3 × 4 | **Should be primary but isn't** |
| **Recent win rate (last 20 trades)** | **8×** | (WR - 0.5) × 8 | **SELF-REINFORCING DOOM LOOP** |
| Profit factor | 2× | (PF - 1.0) × 2 | OK weight |
| Consecutive loss penalty | 0.5/loss, max 3 | consec × 0.5 | Piles on |
| Choppy override | 2 of 3 signals | WR<42%, hold<45min, BTC±1.5% | Almost always triggers |

**The regime detector uses the bot's OWN win rate (8× weight) as its primary signal.** When the bot loses → WR drops → regime=choppy → tighter params → more losses → WR drops more → stuck in choppy **FOREVER**. Even if BTC is +3% bullish, a 20% bot WR gives: `(3/3)×4 + (0.20-0.5)×8 = 4 - 2.4 = 1.6` → "sideways", then choppy override fires because WR<42%.

---

## Root Causes (ranked by dollar impact)

1. **`early_thesis_invalid` exit: -$863** — 0% WR across 31 trades. Kills positions in 5-12 minutes before trailing stop can capture any move. The positions it kills would have hit -3.5% SL anyway (saving ~$5-10 each at most), but it prevents ANY from recovering.

2. **Regime feedback doom loop: -$500+ indirect** — WR-based regime detection creates self-reinforcing choppy classification. Bot's poor performance → choppy regime → worse parameters → worse performance.

3. **Position size death spiral: -$400+ indirect** — Choppy(0.55×) × Volatile(0.80×) × Drawdown-scaling = ~0.35× base size. Avg margin dropped from $467 to $65. Even wins only produce $5-20, can't offset losses.

4. **Choppy SL scaling too tight: -$200+ indirect** — -3.5% × 0.65 = -2.28% SL. With 7x leverage, a 0.33% price move (pure market noise) triggers stop.

---

# Three Strategy Proposals

## Strategy A: "Quick Fix" — Remove the Poison, Keep the System

**Philosophy:** The trailing stop system works (57% WR, +$578). Just stop killing trades before it can activate.

| Change | From | To | Why |
|---|---|---|---|
| Remove `early_thesis_invalid` | Active (5min, -1%, peak<0.3%) | **DISABLED** | 0% WR, -$863, kills 41% of trades |
| Flatten SL regime scaling | choppy: ×0.65 = -2.28% | **All regimes: -3.5% flat** | -2.28% is noise with 7x leverage |
| Fix regime detector | WR weight=8× | **WR weight=2×, BTC weight=6×** | Break the doom loop |
| Remove volatile size overlay stacking | choppy×volatile = 0.44× | **Max of regime OR volatile, not both** | Stop double-counting |
| Min position margin | $65 | **$150 floor** | Wins need to be meaningful |

**Expected:** WR stays 25-30%, but avg win returns to $80-150 range. ~15-20 trades/day. Break-even at 1 win per 3 losses.

**Risk:** Low. Minimal code changes, removes proven-bad components.

---

## Strategy B: "Sniper" — Fewer Trades, Bigger Bets, Higher Conviction

**Philosophy:** Quality over quantity. The money-printer had 4 trades, not 40. Trade less, size up.

| Change | From | To | Why |
|---|---|---|---|
| Remove `early_thesis_invalid` | Active | **DISABLED** | Same as A |
| Raise entry bar dramatically | ta≥35, posterior≥0.40 | **ta≥55, posterior≥0.55** | Only top-tier setups |
| Max positions | 4-12 (regime) | **3 max, all regimes** | Force concentration |
| Position size | 8% margin cap | **12-15% margin cap** | Each trade matters |
| Leverage | 7x default | **5x default** | Wider stops, less noise |
| SL | -3.5% (regime-scaled) | **-4.0% flat** | With 5x lev, -4% = 20% equity. Room to breathe |
| Trailing activate | 1.0% | **1.5%** | Let trades develop |

**Expected:** 5-10 trades/day, $300+ margin each. WR 30-40%. Avg win $100-200, avg loss $60-80. Consistent grinder.

**Risk:** May miss some moves. Slower capital deployment.

---

## Strategy C: "Wave Rider" — Binary Trend Switch (RECOMMENDED)

**Philosophy:** Exactly what you described: *"hop on the uptrend, make some good, once trend slows down close it off, repeat."* Replace the entire complex regime/mode/overlay machinery with one simple rule:

> **BTC trending up → trade aggressively. BTC NOT trending → 100% cash.**

| Change | From | To | Why |
|---|---|---|---|
| **BTC Trend Master Switch** | 4-regime system | **Binary: BTC EMA9>EMA21 + RSI>45 → ON, else OFF** | Simple, market-based, no feedback loop |
| When ON | Regime-scaled everything | **Full size, full positions, 6x lev, -3.5% SL** | Aggressive when conditions are right |
| When OFF | Trade in choppy with tiny size | **ZERO new entries. Let existing ride trailing** | Cash IS a position |
| Remove `early_thesis_invalid` | Active | **DISABLED** | Same as A and B |
| Remove regime scaling on exits | choppy SL=-2.28% | **-3.5% flat always** | Consistent risk |
| Position size | 0.44× in choppy | **8-10% margin when ON, 0% when OFF** | Binary, not gradual |
| Trailing stop | 1.0% activate, 1.0% dist | **1.2% activate, 1.0% dist** | Slight breathing room |
| Max positions when ON | 4 (choppy) | **6** | Deploy capital when trend is confirmed |

**Expected:** Trading maybe 8-16 hours per day during uptrends. Sitting in cash during chop (MUCH better than bleeding -$1,374). When trading, WR 35-45% with avg win $100-200 (trailing captures full wave). Drawdown limited to trend reversals only.

**Risk:** May sit idle during false-start rallies. But as we saw — 3 hours idle was infinitely better than 76 trades of bleeding.

---

## My Recommendation: **Strategy C (Wave Rider)**

Why:
1. **It matches your mental model** — "hop on uptrend, make money, close when done"
2. **It eliminates ALL three root causes** — no early_thesis kills, no regime feedback loop, no size death spiral
3. **It's the simplest** — one binary check replaces hundreds of lines of regime/mode/overlay logic
4. **The data proves it** — the 4 money-printing trades happened when the bot just rode the trend with trailing stops. Strategy C is literally: do that, and only that.
5. **Cash when unsure > bleeding when unsure** — 3 hours idle lost $0. 72 choppy trades lost $1,795.

Want me to implement Strategy C? I can have it coded, tested, and deployed within this session.