# Moonshot-CEX — Changelog

All notable changes, bug fixes, strategy improvements, and configuration overhauls are documented here.  
Format: **version → date → category → what changed → why**.

---

## v3.3 — March 23–24, 2026 — Momentum Capture & Re-entry Overhaul

> **Mission:** Bot was missing clear momentum pumps (SOL +5%, BTC +3%), exiting winners too early, and — after a market crash — **refusing to re-enter** even when the reversal was obvious. Two sessions of targeted fixes across watcher, analyzer, position manager, and BigBrother regime config.

---

### CRITICAL BUG FIX — Bot Refused All Entries After Market Crash

#### 1. `CHOPPY_MIN_TA_SCORE = 82` — unreachable gate, killed all re-entries
- **File:** `src/bigbrother.py`
- **Bug:** `CHOPPY_MIN_TA_SCORE = 82.0` was applied to **both** `bear` and `choppy` regimes. Any candidate with `ta_score < 82` was rejected before position sizing.
- **Real-world impact:** After the bot correctly sold all positions during a sharp market drop, the market reversed/bounced. Bot was supposed to re-enter. Instead, every single candidate was blocked:
  ```
  SOL/USDT skipped: choppy regime requires ta_score >= 82 (got 52)
  BTC/USDT skipped: choppy regime requires ta_score >= 82 (got 47)
  TAO/USDT skipped: choppy regime requires ta_score >= 82 (got 58)
  KAT/USDT skipped: choppy regime requires ta_score >= 82 (got 48)
  ```
  Bot sat **fully in cash** through the entire reversal bounce.
- **Root cause:** In a bear/choppy regime, TA signals are inherently weaker — EMAs lagging, RSI depressed, MACD negative. Achievable ta_scores are typically 45–65. The gate of 82 (written as a "quality enforcer") was effectively infinity — mathematically impossible to pass.
- **Fix:** `CHOPPY_MIN_TA_SCORE: 82.0 → 50.0`
  - 50 still gates low-noise false signals (random alts that barely qualify)
  - Allows SOL (52), TAO (58), BTC (47→50+ on reversal) through
  - **Not overfitting** — 82 was provably wrong. 50 is a reasonable noise floor.

#### 2. `choppy` allowlist missing `"momentum"` setup type
- **File:** `src/bigbrother.py` — `REGIME_SETUP_ALLOWLIST`
- **Before:** `"choppy": {"breakout", "momentum_short"}` — no momentum longs allowed in choppy
- **Problem:** Momentum reversals (the single best trade during a recovery) were blocked by setup type alone, before even reaching the ta_score gate.
- **Fix:** `"choppy": {"breakout", "momentum", "momentum_short"}`
- **Safety unchanged:** `pullback` and `mean_reversion` remain excluded — dip-buying in choppy conditions still blocked.

---

### STRATEGY CHANGES — Momentum Wave Capture

#### 3. Watcher scoring: 1h price return added, volume dominance reduced
- **File:** `src/watcher.py` — `_score_symbol()`
- **Problem:** Watcher was scoring tokens heavily on volume spike (max 60pts) and ignoring whether price was actually moving. Result: tokens with big volume but flat/down price scored high and got through to the analyzer. SOL pumping +5% with moderate volume scored lower than a random alt with a volume spike.
- **Changes:**
  - Volume spike: `60pts → 40pts max` (still important, just not dominant)
  - 24h trend bonus: `15pts → 25pts` (sustained trend = real momentum)
  - **New: 1h price return scoring** (up to 35pts):
    ```
    ≥5.0% → 35pts   |  ≥3.0% → 25pts
    ≥2.0% → 18pts   |  ≥1.0% → 10pts
    ≥0.5% → 5pts    |  <0.5% → 0pts
    ```
- **Effect:** Tokens that are ACTUALLY pumping now score first. Volume-heavy-but-flat tokens get deprioritized.

#### 4. Analyzer: RSI cap raised — peak momentum tokens no longer rejected
- **File:** `src/analyzer.py`
- **Before:** `RSI > 82` → rejected. Tokens like SOL at RSI 84-88 (mid-pump) were blocked.
- **Problem:** Momentum tokens at RSI 82+ are NOT overbought — they're in the momentum acceleration zone. RSI 82 = still buying pressure. RSI 95+ = potential exhaustion.
- **Fix:** `RSI cap: 82 → 92`. Updated `_classify_setup()` bounds to match.
- **Effect:** SOL, BTC, TAO at peak momentum RSI (83–90) no longer rejected.

#### 5. Analyzer: timeframe weights rebalanced — less 4h lag, more 15m/5m
- **File:** `src/analyzer.py`
- **Before (approximate):** `{"5m": 0.10, "15m": 0.20, "1h": 0.35, "4h": 0.35}`
- **After:** `{"5m": 0.15, "15m": 0.30, "1h": 0.35, "4h": 0.20}`
- **Rationale:** 4h is a lagging confirmation signal — by the time 4h confirms momentum, the move is 60-70% done. 15m and 5m catch moves as they happen. 1h stays dominant for trend context. 4h drops to directional filter only.

#### 6. Momentum fast-track — bypass EMA/MACD gates on proven price action
- **File:** `src/analyzer.py` — `_analyze_symbol()`
- **What:** If a token's 1h return (derived from 5m closes) ≥ 2.0%, skip EMA9>EMA21 check and MACD confirmation entirely. Log `FAST-TRACK`.
- **Why:** When price is already pumping 2%+, lagging indicators (EMAs, MACD) haven't crossed yet. Waiting for them = missing the move. The price pump IS the signal.
- **Guard:** Fast-track still respects RSI bounds, volume gates, regime allowlist, Bayesian threshold, and SL/cooldown logic. It's not a free pass — just skips the two lagging gates.
- **Real-world result (verified in logs):**
  ```
  DGB/USDT FAST-TRACK: 1h return +5.6% — bypassing EMA/MACD gates
  KAT/USDT FAST-TRACK: 1h return +7.2% — bypassing EMA/MACD gates
  AR/USDT  FAST-TRACK: 1h return +2.7% — bypassing EMA/MACD gates
  WIF/USDT FAST-TRACK: 1h return +2.7% — bypassing EMA/MACD gates
  ```
- **Overfitting risk: MEDIUM.** Could enter already-topped pumps. Mitigated by -5% stop loss and -3%/15min hard loss cut. Monitor: if fast-track entries consistently exit via hard_loss_cut, raise threshold to 3%.

#### 7. `no_traction` exit — changed from full kill to 50% partial exit
- **File:** `src/position_manager.py` — `_tick_position()`
- **Before:** `no_traction` = full position close. Entire trade killed.
- **Problem:** A position flagged for no_traction at -1.5% at 30min may still be a valid setup that just started slow. Killing 100% removes all upside if the momentum comes at minute 35.
- **Fix:** `no_traction` now executes a **50% partial exit** (same as `momentum_died/stall`). 50% sold to lock in downside protection; 50% remains for the potential momentum leg.

#### 8. `hard_loss_cut` relaxed — stop nuking SOL before it pumps
- **File:** `src/position_manager.py` — `_tick_position()`
- **Before:** `-2% / 10 min` — if -2% within 10 min and never reached +0.5%, cut immediately
- **Problem:** SOL (and most large caps) routinely dip -2% in the first 10 minutes before beginning a 5%+ move. This threshold was killing winners before they started.
- **Fix:** `-3% / 15 min` — gives the position another 5 min and another 1% of breathing room. Still cuts genuinely dead positions; stops nuking legit momentum entries on entry noise.

---

### OPERATIONAL FIX — Session Churn Guard

#### 9. New: `is_symbol_churning()` — max 3 entries per symbol per 4-hour window
- **Files:** `src/position_manager.py`, `backend/server.py`
- **Problem discovered:** Historical logs showed TRX/USDT entered **16 times** and ANIME/USDT **14 times** in a single session. Each failed at -0.3% to -0.8% with a small dollar loss. Losses were small per-trade but **cumulative fee erosion and repeated capital allocation to losers** was significant.
- **Root cause:** When base cooldown was short (10–30 min in earlier sessions), a token could be re-entered every ~20 min indefinitely. TRX kept scoring well on volume/RSI indicators but wasn't actually moving.
- **Fix:** Rolling 4-hour entry count per symbol. If a symbol has been entered **3+ times in the last 4 hours**, it is blocked from new entry:
  ```
  [Swarm] TRX/USDT skipped: churn guard (3+ entries in 4h)
  ```
- **Implementation:** `_symbol_entry_times: dict[str, list[float]]` in PM. `_record_entry()` called on every successful open. `is_symbol_churning()` called in server cycle gate immediately after cooldown check.
- **Not overfitting** — pure capital protection. Prevents the bot from allocating $1,000+ per cycle to a token that has already failed 3 times today.

---

### CONFIGURATION CHANGES (v3.3)

| Parameter | Old Value | New Value | File |
|-----------|-----------|-----------|------|
| `CHOPPY_MIN_TA_SCORE` | `82.0` | `50.0` | `src/bigbrother.py` |
| Choppy `REGIME_SETUP_ALLOWLIST` | `{breakout, momentum_short}` | `{breakout, momentum, momentum_short}` | `src/bigbrother.py` |
| Analyzer RSI cap | `82` | `92` | `src/analyzer.py` |
| TF weight `4h` | `~0.35` | `0.20` | `src/analyzer.py` |
| TF weight `15m` | `~0.20` | `0.30` | `src/analyzer.py` |
| TF weight `5m` | `~0.10` | `0.15` | `src/analyzer.py` |
| Watcher volume spike max pts | `60` | `40` | `src/watcher.py` |
| Watcher 24h trend bonus max | `15` | `25` | `src/watcher.py` |
| Watcher 1h return scoring | *(not present)* | `0–35pts` | `src/watcher.py` |
| `no_traction` exit | Full close | 50% partial | `src/position_manager.py` |
| `hard_loss_cut` threshold | `-2% / 10 min` | `-3% / 15 min` | `src/position_manager.py` |
| Session churn guard | *(not present)* | max 3 entries / 4h | `src/position_manager.py`, `backend/server.py` |
| `SYMBOL_COOLDOWN_MINUTES` | `~30` (was too short) | `90` | `.env` |

---

### WHAT WORKED ✅

1. **Crash detection + full exit** — Bot correctly identified regime shift to `bear`, swept all positions, minimized drawdown during the sharp market drop.
2. **Reversal re-entry (post-fix)** — Within 20 seconds of the CHOPPY_MIN_TA_SCORE fix and restart, bot opened **8 positions** on the reversal bounce: SOL, BTC, TAO, AR, DGB, MEME, FIDA, FARM.
3. **Fast-track detection** — DGB (+5.6%), KAT (+7.2%), AR (+2.7%), WLFI (+2.3%) all correctly identified and fast-tracked.
4. **Regime transitions** — bear → sideways → bull transition handled cleanly. No position state corruption.
5. **1h return scoring in watcher** — Meaningfully changed which tokens top the candidate list. Price-momentum tokens now rank ahead of volume-spike-only tokens.

### WHAT FAILED / NEEDED ITERATION ❌

1. **`CHOPPY_MIN_TA_SCORE = 82` (set in v3.2) — the gate that ate itself**
   - Intended as a quality enforcer for bear/choppy entries. In practice, scores of 82+ are essentially unreachable in a depressed market (achievable range: 45–65). Created a logic bomb that silently blocked 100% of candidates.
   - Lesson: Quality gates must be calibrated against what's actually achievable. Hard floors need empirical validation, not guesswork.

2. **`SYMBOL_COOLDOWN_MINUTES` — was effectively 10–30 min in earlier sessions**
   - Resulted in TRX/ANIME being entered 16 and 14 times respectively. Cooldown logs showed "15m for stop-loss" when it should have been 135m (at 90-min base × 1.5). Root cause: the .env value had been edited down at some point without awareness of the multiplier structure.
   - Current value: 90 min base. Effective cooldowns: momentum_died = 60m, stop_loss = 135m, no_traction = 90m.
   - Session churn guard added as a second safety net independent of cooldown value.

3. **XRP/USDT IOC SL bug (prior session, already fixed)**
   - Stop loss placed as IOC limit order. Exchange rejected it. Bot had no fallback to market sell. Position held through the entire -18% SL trigger zone, generating a -$747 realized loss (single largest loss in session history). Fixed: SL execution now falls back to market order after IOC rejection.

4. **`no_traction` as full kill — too aggressive on slow starters**
   - The v3.2 threshold loosening (30min/-2%) helped but the 100% kill was still costing upside on tokens that eventually moved. Converted to 50% partial — reduces exposure on stalling positions while preserving optionality.

---

### CURRENT STATUS (March 24, 2026 — 02:42 UTC+8)

```
Regime:        bull → mode: normal
Open positions: 8 of 8 max (SOL, BTC, ETH, AR, TAO, ZEC, DGB, BNSOL family)
Unrealized PnL: +$284.98
NAV:            ~$13,128 (+$265 session)
Drawdown:       7.2% from peak (dd_mult = 0.60× on sizing)
Cooldown base:  90 min
Churn guard:    active (3 entries / 4h per symbol)
Fast-track:     active (>2% 1h return bypasses EMA/MACD)
```

**All fixes deployed and running. Bot is actively scanning 446 pairs per cycle and executing on momentum signals.**

---

### FILES MODIFIED IN v3.3

| File | Changes |
|------|---------|
| `src/bigbrother.py` | `CHOPPY_MIN_TA_SCORE` 82→50, choppy allowlist added `"momentum"` |
| `src/analyzer.py` | RSI cap 82→92, TF weights rebalanced, momentum fast-track logic, `_classify_setup` RSI bounds updated |
| `src/watcher.py` | 1h return scoring (0–35pts), volume spike cap 60→40, 24h trend bonus 15→25 |
| `src/position_manager.py` | `no_traction` → 50% partial, `hard_loss_cut` -2%/10m → -3%/15m, `is_symbol_churning()`, `_record_entry()`, `_symbol_entry_times` tracking |
| `backend/server.py` | Churn guard gate (`is_symbol_churning`) wired after cooldown check in `_run_cycle` |
| `.env` | `SYMBOL_COOLDOWN_MINUTES` confirmed at 90 |

---

## v3.2 — March 23, 2026 — Profitability Overhaul

> **Mission:** Stop the bleeding. Make the bot a money printer, not a bullock cart.  
> Root cause analysis identified 10+ systematic issues causing losses. All fixed in this release.

---

### BUG FIXES

#### 1. `is_aggressive` flag — permanently broken (silent bug)
- **File:** `src/position_manager.py`, `backend/server.py`
- **Bug:** `is_aggressive` checked `regime_params.get("max_exposure_pct", 1.0) <= 0.40`. The `regime_params` dict comes from `_build_regime_params()` (exit-scaling dict: stop/trail/time fields only) — it **never contained `max_exposure_pct`**. So the default `1.0` was always returned → `1.0 <= 0.40 = False` → `is_aggressive` was permanently `False` in all regimes.
- **Effect:** Bear/choppy positions used the slow non-aggressive exit path (45 min / -2.5%) instead of the fast path (15 min / -0.5%). Short tokens never got their tight management.
- **Fix:** Injected `regime_params["regime"] = STATE.get("regime")` in `_tick_positions()`. Changed check to `regime_params.get("regime") in ("bear", "choppy")`. Explicit name check, impossible to break by threshold drift.

#### 2. Bayesian threshold INVERTED in `.env` (critical)
- **File:** `.env`
- **Bug:** `.env` had `BAYESIAN_THRESHOLD_VOLATILE=0.38`. The code default was `0.45` (normal). So in bear/volatile mode, the entry bar was **easier** than in normal mode (`0.38 < 0.45`). Every mediocre setup passed in the worst market conditions.
- **Effect:** Bot was over-trading bad setups precisely when the market was most dangerous.
- **Fix:** `BAYESIAN_THRESHOLD_VOLATILE: 0.38 → 0.52` (higher than normal = stricter in volatile markets, as intended).

#### 3. `.env` overriding code fixes silently
- **File:** `.env`
- **Bug:** Several `.env` values were negating Python-level fixes because `.env` always wins over `Field(default=...)`:
  - `BAYESIAN_THRESHOLD_VOLATILE=0.38` — overriding `0.52` fix in `config.py`
  - `BAYESIAN_THRESHOLD_SAFETY=0.55` — overriding `0.58` fix
  - `ANALYZER_MIN_SCORE=20` — overriding `30` fix
- **Fix:** Updated all three in `.env` directly. Rule: always patch `.env` alongside `config.py` defaults.

#### 4. Duplicate `MAX_DRAWDOWN_PCT` in `.env` — ambiguous which value wins
- **File:** `.env`
- **Bug:** `MAX_DRAWDOWN_PCT=25.0` (line 119) and `MAX_DRAWDOWN_PCT=0.35` (line 199). The first entry (`25.0`) is treated as a decimal by the code — it means a 2500% drawdown tolerance, effectively disabling the drawdown circuit breaker.
- **Fix:** Removed the `25.0` duplicate. Only `MAX_DRAWDOWN_PCT=0.35` (35% tolerance in decimal) remains.

#### 5. `MAX_DAILY_LOSS_USD=5.0` — $5/day hard cap halting the bot
- **File:** `.env`
- **Bug:** `MAX_DAILY_LOSS_USD=5.0` was set in `.env`. The bot stops entering new positions after $5 cumulative daily loss — equivalent to one normal fee on a medium position.
- **Fix:** Removed this field entirely. Daily loss is already controlled by `DAILY_LOSS_LIMIT_PCT=0.25` (25% of equity = $3,000 on a $12K account).

#### 6. `momentum_recheck_interval_minutes` — not wired to `PositionManager`
- **File:** `backend/server.py`
- **Bug:** `PositionManager.__init__` accepts `momentum_recheck_interval_minutes` but `server.py` was not passing it. The PM always used its hardcoded default of 5 minutes regardless of config/env.
- **Fix:** Added `momentum_recheck_interval_minutes=cfg.momentum_recheck_interval_minutes` to the PM constructor call. Also added `MOMENTUM_RECHECK_INTERVAL_MINUTES=30` to `.env`.

#### 7. TAO/USDT ghost-position looping on dust
- **File:** `src/position_manager.py`
- **Bug:** A dust residual position (0.000465 TAO = ~$0.13) was looping on every cycle — attempting to place a limit sell, getting rejected by exchange min order size, logging a GHOST-CLOSE, and repeating. Never cleared from DB.
- **Fix (prior session):** Added dust guard in `scale_position`: skip scale-up if position value < `$50`. Ghost-close marks position as closed in DB on dust rejection.

---

### STRATEGY CHANGES

#### 8. Bear/choppy regime: blanket long ban → dual-side trading
- **File:** `src/bigbrother.py`
- **Before:** `REGIME_SETUP_ALLOWLIST` for bear/choppy was `{momentum_short}` only. Zero long entries allowed.
- **Problem:** Missed all relative-strength plays — tokens outperforming the market in a bear (sector rotation, narrative catalysts). Capital sat idle.
- **After:**
  - `bear`: `{breakout, momentum, momentum_short}` — relative-strength longs + short tokens simultaneously
  - `choppy`: `{breakout, momentum_short}` — only the cleanest breakout signal for longs + short tokens
- **Safety maintained by:** 4h EMA50 trend gate (per-token filter in `analyzer.py`) blocks trend-fighting longs. Bayesian 0.52 threshold ensures only high-conviction entries. `CHOPPY_MIN_TA_SCORE=82.0` enforces quality.
- **Excluded from bear/choppy:** `pullback`, `mean_reversion`, `consolidation_breakout` — these are dip-buying setups that bleed in downtrends.

#### 9. Bear/choppy capital deployment — from near-zero to functional
- **File:** `src/bigbrother.py` — `REGIME_CAPITAL`
- **Before → After:**

  | Regime   | Max Exposure (before) | Max Exposure (after) | Size Mult (before) | Size Mult (after) |
  |----------|----------------------|---------------------|--------------------|-------------------|
  | Bull     | 90%                  | 90%                 | 1.00×              | 1.00×             |
  | Sideways | 75%                  | 82%                 | 0.85×              | 0.92×             |
  | Bear     | 80% → 20%            | **55%**             | 0.95× → 0.40×      | **0.65×**         |
  | Choppy   | 65% → 15%            | **42%**             | 0.85× → 0.30×      | **0.55×**         |

- **Note:** v3.1 set bear to 80% (too aggressive). This session initially overcorrected to 20% (too conservative). Settled at 55% as the right balance for dual-side deployment.

#### 10. Max concurrent positions per regime
- **File:** `src/bigbrother.py` — `REGIME_MAX_POSITIONS`
- **Before → After:** bull: 10→10, sideways: 8→8, bear: 2→6, choppy: 2→4
- **Rationale:** 2 positions in bear at 55% capital cap = up to 27% per trade (too concentrated). 6 positions spreads risk across both longs and shorts.

#### 11. Bayesian thresholds — regime-specific overrides
- **File:** `src/bigbrother.py` — `REGIME_BAYESIAN_THRESHOLD`
- **Added:** `bear: 0.52`, `choppy: 0.55` (both higher than the normal 0.45 threshold)
- **Rationale:** More selective entry bar in dangerous regimes. The higher the uncertainty, the higher the conviction required.

#### 12. 4h EMA50 trend gate for long entries
- **File:** `src/analyzer.py`
- **What:** Before computing a full TA score, check if `price < 4h_EMA50 × 0.99` (with 1% tolerance). If so, return `None` — candidate dropped before analysis.
- **Why:** Long-only momentum bots bleed in downtrends. This gate ensures longs only fire on tokens that are in a confirmed uptrend on the 4h timeframe — i.e., genuine relative-strength plays.
- **Dynamic:** Per-token check, not regime-level. A token can be above its own 4h EMA50 even during a bear market (sector rotation, narrative plays). These are the best longs to trade.
- **Short tokens:** Bypass this gate entirely (`direction == "long"` check). Short token ETFs are always valid candidates in bear mode.

#### 13. Minimum 2% stop distance enforcement
- **File:** `src/analyzer.py` — `_compute_entry_zone()`
- **Before:** ATR-based stops with no floor. On low-volatility tokens in quiet hours, ATR produced stops as tight as 0.5-0.8% from entry.
- **Problem:** Normal tick noise (0.5-1% intrabar moves) triggered stops constantly. Each stop-out = loss + cooldown = frozen capital.
- **After:** `min_risk = entry × 0.02`. If `risk_per_unit < min_risk`, widen stop to 2% and recalculate TP1 (2R) and TP2 (4R) proportionally.
- **Effect:** Positions survive normal market noise; stops only fire on genuine adverse moves.

#### 14. Exit timing — the "chop machine" death loop fix
- **File:** `src/position_manager.py`
- **Before (non-aggressive = bull/sideways):**
  - `no_traction`: exit at 15 min if down -0.5%
  - `momentum_stall`: exit at 30 min if down -1.0%
  - `_momentum_exit_reason` first check: 5 min / -1.0%
  - `_momentum_exit_reason` second check: 10 min / -0.5%
- **Problem:** Every crypto position dips -0.5% at some point in the first 15 minutes. This created a `buy → noise dip → cut → rebuy → repeat` loop generating hundreds of small losses with zero winners ever being held.
- **After (non-aggressive = bull/sideways):**
  - `no_traction`: 30 min / -2.0% (6× more patience)
  - `momentum_stall`: 45 min / -2.5%
  - `_momentum_exit_reason` first check: 30 min / -1.5%
  - `_momentum_exit_reason` second check: 60 min / -1.0%
- **Aggressive path (bear/choppy) unchanged** — short tokens need tight management.

#### 15. Watcher short-token quota — regime-aware
- **File:** `src/watcher.py`
- **Before:** `n_shorts = max(2, top_n // 4)` always (25% of pipeline regardless of regime)
- **After:** `n_shorts = max(2, top_n // 3)` in bear/choppy (33%), `// 4` in bull/sideways
- **Rationale:** In dual-side bear mode, short tokens compete equally with longs. Giving them only 25% of slots meant they'd be crowded out when long signals were abundant.

#### 16. Analyzer pipeline throughput
- **File:** `src/config.py` / `.env`
- **Before:** `analyzer_top_n=5` — only 5 setups analyzed per cycle
- **After:** `analyzer_top_n=12` — 12 setups analyzed
- **Rationale:** With up to 10 positions allowed (bull) and the 4h EMA50 gate now filtering some longs, the pipeline needed more candidates. 5 candidates → 2-3 pass filters → can't fill 6-10 positions without increasing throughput.

#### 17. Bayesian safety threshold raised
- **File:** `.env` / `src/config.py`
- **`BAYESIAN_THRESHOLD_SAFETY`: `0.55 → 0.58`**
- BigBrother's safety mode (triggered by drawdown + bad macro LLM signal) now requires even higher conviction. Drawdown events = be more selective, not less.

#### 18. `CONSECUTIVE_LOSS_PAUSE_MINUTES`: `3 → 15`
- **File:** `.env`
- 3 minutes is not a pause — it's a blink. After 5 consecutive losses, give the strategy 15 minutes to let conditions change before re-entering.

---

### CONFIGURATION CHANGES SUMMARY (`.env` and `config.py`)

| Parameter | Old Value | New Value | File |
|-----------|-----------|-----------|------|
| `BAYESIAN_THRESHOLD_VOLATILE` | `0.38` | `0.52` | `.env` |
| `BAYESIAN_THRESHOLD_SAFETY` | `0.55` | `0.58` | `.env` |
| `ANALYZER_MIN_SCORE` | `20` | `30` | `.env` |
| `MOMENTUM_RECHECK_INTERVAL_MINUTES` | *(not set, default 5)* | `30` | `.env` |
| `CONSECUTIVE_LOSS_PAUSE_MINUTES` | `3` | `15` | `.env` |
| `MAX_DRAWDOWN_PCT` | `25.0` (duplicate) | removed | `.env` |
| `MAX_DAILY_LOSS_USD` | `5.0` | removed | `.env` |
| `time_exit_hours` | `4.0` | `6.0` | `config.py` |
| `bayesian_threshold_volatile` | `0.38` | `0.52` | `config.py` |
| `bayesian_threshold_safety` | `0.55` | `0.58` | `config.py` |
| `momentum_recheck_interval_minutes` | `5` | `30` | `config.py` |
| `analyzer_top_n` | `5` | `12` | `config.py` |
| `watcher_top_n` | `20` | `30` (`.env` already 60) | `config.py` |

---

### FILES MODIFIED IN v3.2

| File | Changes |
|------|---------|
| `src/bigbrother.py` | `REGIME_CAPITAL`, `REGIME_SETUP_ALLOWLIST`, `REGIME_BAYESIAN_THRESHOLD`, `REGIME_MAX_POSITIONS`, `CHOPPY_MIN_TA_SCORE`, `choppy_min_ta_score` applied to both bear+choppy |
| `src/config.py` | `bayesian_threshold_volatile`, `bayesian_threshold_safety`, `time_exit_hours`, `momentum_recheck_interval_minutes`, `analyzer_top_n`, `watcher_top_n` |
| `src/analyzer.py` | 4h EMA50 trend gate, 2% minimum stop distance |
| `src/position_manager.py` | `is_aggressive` fix (both locations), `no_traction` / `momentum_stall` thresholds + timing, `_momentum_exit_reason` non-aggressive thresholds |
| `src/watcher.py` | Short-token quota regime-aware (`top_n // 3` in bear/choppy) |
| `backend/server.py` | `momentum_recheck_interval_minutes` wired to PM, `regime` key injected into `regime_params` for `is_aggressive` fix |
| `.env` | `BAYESIAN_THRESHOLD_VOLATILE`, `BAYESIAN_THRESHOLD_SAFETY`, `ANALYZER_MIN_SCORE`, `MOMENTUM_RECHECK_INTERVAL_MINUTES`, `CONSECUTIVE_LOSS_PAUSE_MINUTES`, removed `MAX_DRAWDOWN_PCT` duplicate, removed `MAX_DAILY_LOSS_USD` |

---

## v3.1 — March 2026 — Capital Deployment Overhaul

> **Mission:** Position sizes were $4-9 on a $12K account. Fix the sizing engine.

### Bug Fixes
- **Kelly sizing floor:** `_kelly_size()` fallback was `max_risk_per_trade` (tiny %) instead of `max_single_exposure` (20%). Zero-win-history = zero size.
- **Tier multiplier normalization:** `tier_mult = kelly_mult / 0.50` so small=1.0×, medium=1.5×, large=1.8×. Before: all tiers were effectively 1.0×.
- **`detect_account_tier()` not called:** `compute_position_size()` used stale tier data from initialization. Now called at the top of every sizing computation.
- **Minimum order floor raised:** `$10 → $50` to match exchange minimums and ensure positions are meaningful.

### Strategy Changes
- `MAX_PORTFOLIO_EXPOSURE_PCT: 0.85 → 0.95`
- `MAX_SINGLE_EXPOSURE_PCT: 0.15 → 0.25`
- `MAX_RISK_PER_TRADE_PCT: 0.06 → 0.08`
- `MAX_POSITIONS: 5 → 8`
- Bear `REGIME_CAPITAL`: `max_exposure=0.80, size_mult=0.95` (reduced in v3.2 to 0.55/0.65)
- Conviction floor raised to `0.55` (was `0.70` — blocking most entries)

---

## v3.0 — March 2026 — Exchange-First Architecture

- All financial metrics (equity, PnL, positions) sourced from exchange; MongoDB used for infra only
- FIFO realized PnL calculation (`_compute_pnl_from_fills`)
- `compute_position_size()` gains `posterior`, `threshold`, `vol_usd`, `ta_score` inputs
- Conviction multiplier (0.55× → 1.45×), liquidity multiplier (0.45× → 1.00×), TA quality multiplier (0.90× → 1.10×)
- Bayesian engine: replaced `× 6.5` normalisation with correct Bayes theorem
- `mean_reversion` prior lowered `0.52 → 0.38`
- Frontend NAV Chart with Session/1H/6H/1D/7D intervals

---

## v2.0 — March 2026

- Exchange holdings receive stop loss + trailing stop + time exit protection
- Limit-first exit execution (reprice up to 5× before aggressive limit)
- Symbol cooldown after stop-loss exits (prevents revenge trading)
- FIFO PnL in trade history endpoint

---

## v1.0 — Initial Release

- Multi-agent swarm: Watcher, Analyzer, Context, Bayesian, Execution, Position, Risk, QuantMutator, BigBrother
- Paper / demo / live mode support
- Gate.io, Binance, KuCoin via CCXT
- Next.js dashboard + TinyOffice chat interface
- MongoDB persistence + Redis caching
- Prometheus metrics + Discord/Telegram alerts
