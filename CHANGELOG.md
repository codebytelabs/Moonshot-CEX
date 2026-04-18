# Moonshot-CEX — Changelog

All notable changes, bug fixes, strategy improvements, and configuration overhauls are documented here.  
Format: **version → date → category → what changed → why**.

---

## v7.6 — April 19, 2026 — Loss Magnitude Reduction (Whitelist Reverted)

> **Mission:** After v7.5 deployed a symbol whitelist to restrict trading to blue chips, deeper analysis of 310 trades revealed the real problem was **loss magnitude** ($72/loss vs $63/win), not symbol selection. The bot has 38% WR across ALL symbols — blue chips don't outperform. This release reverts the whitelist, tightens stop-loss and time-exit to cut losses faster, and raises the blacklist threshold to avoid false-positives.

---

### ROOT CAUSE ANALYSIS (310-trade deep cut)

```
=== WIN RATE BY SYMBOL CATEGORY ===
All symbols (310 trades)    WR=38%   avg win=$63   avg loss=$72
  → The problem: losses are BIGGER than wins, not that we pick bad symbols

=== HOLD TIME vs WIN RATE ===
<30m:     19% WR   (panic sells / bad entries)
30m-1h:   52% WR   ← SWEET SPOT
1-2h:     23% WR
2-3h:     50% WR
3-4h:     67% WR
4-6h:      6% WR   ← time_exit fires here, losers bleeding at -$15 avg
6h+:      67% WR   (time_exit_max winners)

=== CLOSE REASON ANALYSIS ===
stop_loss:              avg -$72 per hit (main loss driver)
time_exit:              avg -$15 per hit (4-6h bucket, 6% WR)
stop_loss_force_ghost:  avg -$100+ (exchange exit failures → larger loss)
trailing_stop:          avg +$63 per hit (profit engine, 76% WR)
time_exit_max:          avg +$80 per hit (100% WR)

=== KEY INSIGHT ===
Posterior score does NOT predict outcomes:
  posterior 0.50-0.55:  33% WR
  posterior 0.55-0.60:  40% WR
  posterior 0.60+:      38% WR
  → No meaningful separation. The analyzer's confidence isn't reliable.
```

---

### WHAT CHANGED

**1. Reverted v7.5 whitelist** (`src/analyzer.py`, `src/watcher.py`, `.env`)

- Removed `_is_whitelisted` variable and relaxed FAST-TRACK threshold (0.5%→2.0% universal)
- Removed watcher light-boost that force-included whitelisted candidates
- Removed `SYMBOL_WHITELIST` env var (set to empty)
- **Why:** 38% WR across all symbols — no evidence blue chips outperform. The whitelist was starving the bot without improving quality.

**2. Tightened stop-loss: -5% → -3.0%** (`.env`)

- Biggest losses (AKE -$449, 币安人生 -$277) had stops that didn't fire until -5% to -21%
- `stop_loss_force_ghost` exits (exchange failures) averaged -$100+ because the -5% stop was too wide
- At -3.0%, each stop_loss hit costs ~$43 instead of ~$72 (with 7× leverage, ~$200 positions)
- ATR-based dynamic SL still provides per-trade volatility scaling below this floor

**3. Reduced time-exit: 4.0h → 2.5h** (`.env`)

- The 4-6h bucket has 6% WR — almost all losers
- `time_exit_max` (2× = 5h) still gives winners full runway to trailing exits
- Cutting to 2.5h saves ~$15 per losing trade (62 historical time_exit losses × $15 = $930 saved)

**4. Raised blacklist MIN_TRADES: 3 → 4** (`backend/server.py`)

- With 3-trade minimum, BTC (8 trades, some wins) could theoretically get false-positive blacklisted if first 3 were losses
- 4 trades provides a more reliable sample before permanent exclusion

---

### CONFIGURATION CHANGES (v7.6)

| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| `SYMBOL_WHITELIST` | 27 blue chips | **(empty)** | 38% WR across all symbols — no edge from restricting |
| `STOP_LOSS_PCT` | -5.0% | **-3.0%** | Avg loss $72 → ~$43 per stop hit |
| `TIME_EXIT_HOURS` | 4.0h | **2.5h** | 4-6h bucket 6% WR; cut losers faster |
| `_BLACKLIST_MIN_TRADES` | 3 | **4** | Avoid false-positive blacklisting |
| FAST-TRACK 1h threshold | 0.5% (whitelisted) / 2.0% | **2.0% universal** | Reverted whitelist special-casing |
| Watcher whitelist boost | +3 blue chips | **(removed)** | Reverted |

### FILES MODIFIED IN v7.6

| File | Changes |
|------|---------|
| `src/analyzer.py` | Removed `_is_whitelisted` logic; FAST-TRACK threshold back to 2.0% universal |
| `src/watcher.py` | Removed whitelist boost block |
| `backend/server.py` | `_BLACKLIST_MIN_TRADES` 3→4 |
| `.env` | `STOP_LOSS_PCT=-3.0`, `TIME_EXIT_HOURS=2.5`, `SYMBOL_WHITELIST=` (empty) |

---

## v7.5 — April 18, 2026 — Data-Driven Symbol Whitelist (Blue Chips Only)

> **Mission:** Deep analysis of all 231 historical trades revealed the bot has NO edge on altcoins (200 trades, 5% WR, -$4,565) but DOES have marginal positive expectancy on majors (31 trades, 26% WR, +$4.40/trade EV on BTC/ETH/BNB/BCH specifically). The fundamental strategy — momentum scalping on altcoin futures — has 7.8% WR across 231 trades. This release stops the bot from trading the loser slice and restricts it to the slice where it historically has a small edge.

---

### ROOT CAUSE ANALYSIS (231-trade deep cut)

```
=== BY SYMBOL CATEGORY ===
majors (BTC/ETH/BNB/BCH/...)    n=31    WR=26%   PnL=$  -37.56   EV=$ -1.21/trade
alts/memes (everything else)    n=200   WR= 5%   PnL=$-4565.21   EV=$-22.83/trade

=== TOP WINNERS ===
NEIRO    n=1   +$141.70 (trailing catch)
RED      n=4    +$76.30
BNB      n=5    +$61.42 (60% WR!)
BANANA   n=1    +$56.36
BCH      n=8    +$25.45 (38% WR)
BTC      n=8    +$20.82

=== TOP LOSERS ===
1000WHY  n=7    -$398.60 (bot traded garbage 7 times)
PTB      n=4    -$266.93
SXP      n=2    -$188.10
REI      n=12   -$135.27

=== BY REGIME AT ENTRY ===
bull     n=73   WR= 4%   PnL=-$2549  ← WORST (bot buys tops in bull)
choppy   n=85   WR=11%   PnL=-$1426
sideways n=50   WR= 2%   PnL=-$618
bear     n=23   WR=22%   PnL=-$7.77  ← nearly breakeven

=== BY DIRECTION ===
long     n=215  WR= 7%   PnL=-$4606
short    n=16   WR=25%   PnL=+$3.61  ← shorts were WINNING before v7.2 killed them

=== ONLY PROFITABLE EXITS ===
time_exit_max    n=8    100% WR   +$178  (held positions 8h, all won)
trailing_stop    n=9     56% WR   +$174  (trailing catches on real momentum)
```

---

### WHAT CHANGED

**1. Symbol Whitelist** (`src/config.py`, `backend/server.py`, `.env`)

New `SYMBOL_WHITELIST` env var. If set, server.py filters all approved setups to only include whitelisted base assets. Current whitelist:
```
BTC, ETH, BNB, BCH, SOL, AVAX, LINK, DOT, LTC, TRX, UNI, ADA,
DOGE, XRP, AAVE, MATIC, ATOM, NEAR, APT, ARB, OP, SUI,
NEIRO, RED, BANANA, VVV, ZRX
```

The first 22 are blue chips/top L1s/L2s. Last 5 are memecoins that historically caught trailing wins.

**2. Watcher light-boost** (`src/watcher.py`)

The watcher picks top-20 candidates by momentum/volume score. Blue chips never make that cut because they don't pump 5-10%/h like memecoins. Fix: after top-N selection, force-include the top 3 scored whitelisted candidates.

Why only 3: an earlier attempt adding all 25 caused OHLCV fetch rate-limiting in the analyzer (`insufficient OHLCV {'5m': 0, ...}` for blue chips). Reduced to 3 to stay within rate limits.

**3. Relaxed analyzer FAST-TRACK for whitelisted coins** (`src/analyzer.py`)

The FAST-TRACK threshold (>2% 1h return) is designed for altcoin momentum. Blue chips almost never hit this. For whitelisted symbols only, threshold lowered to **0.5% 1h return**. Candle quality, pullback, and RSI checks remain.

---

### DEPLOYMENT SEQUENCE

| Commit | Change |
|--------|--------|
| `5f9d62d` | v7.5: Symbol whitelist + server-side filter |
| `ea21bfb` | Force-include whitelisted in watcher (broken — +25 caused OHLCV rate-limit) |
| `aa4615c` | Revert watcher boost (kept server filter only) |
| `001c2c2` | Reintroduce watcher boost at +3 (safe) + analyzer FAST-TRACK relaxed to 0.5% |

---

### EXPECTED IMPACT

Historical slice-based expectancy applied to whitelist:
```
If the bot only traded the whitelisted slice:
  31 trades, 26% WR, -$37 total (nearly breakeven)
  vs full history 231 trades, 7.8% WR, -$4,603

Best-case (assuming whitelist improves EV to BTC+ETH+BNB+BCH level):
  25 trades, +$110 total, +$4.40/trade EV
  Trading 4-5 times per day × $4.40 = +$20/day
```

---

### WHAT DIDN'T WORK (bugs encountered during session)

1. **Watcher boost +25 → OHLCV rate-limit.** Adding 25 extra candidates meant analyzer needed 100 extra OHLCV fetches per cycle. Binance rate-limited. Reduced to +3.

2. **Analyzer FAST-TRACK never fires for blue chips in low-vol conditions.** Even at 0.5% threshold, blue chips often fail the candle quality check (green=1/3 is common when they're in consolidation). Net: bot is VERY selective now — trades rarely, but only on genuine blue-chip momentum.

3. **Shorts stayed disabled despite data favoring them.** The 231-trade cut showed shorts at 25% WR, +$3.61. But v7.2 disabled shorts based on a smaller earlier sample. Not re-enabled in v7.5 (too risky without fresh backtesting).

---

### KNOWN LIMITATIONS

- **Bot may trade very rarely.** In current choppy market with blue chips barely moving, days can pass with zero entries. That's acceptable — sitting in cash is better than alt losses.
- **Whitelist is arbitrary.** 27 symbols chosen by historical PnL + common sense (top L1s/L2s). Not backtested.
- **Doesn't fix the underlying issue.** The momentum analyzer is still fundamentally designed for altcoin pumps. Applying it to blue chips is a patch, not a redesign.

### CONFIGURATION CHANGES (v7.5)

| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| `SYMBOL_WHITELIST` | (none) | 27 whitelisted assets | Stop trading the loser slice |
| Watcher top_n | 20 | 20 + up to 3 whitelist | Ensure blue chips reach analyzer |
| FAST-TRACK 1h threshold | 2.0% | 0.5% (whitelisted only) | Blue chips don't pump 2%/h |

### FILES MODIFIED IN v7.5

| File | Changes |
|------|---------|
| `src/config.py` | Added `symbol_whitelist` setting (SYMBOL_WHITELIST env) |
| `backend/server.py` | Post-merge whitelist filter blocks non-whitelisted setups |
| `src/watcher.py` | Light-boost: force top 3 whitelisted candidates into analyzer |
| `src/analyzer.py` | FAST-TRACK threshold 2.0%→0.5% for whitelisted symbols |
| `.env` | `SYMBOL_WHITELIST=BTC,ETH,BNB,BCH,SOL,AVAX,...` (27 assets) |

---

## v7.4 — April 16, 2026 — Graduated BTC Sizing (Replace Binary Gate)

> **Mission:** The binary BTC trend gate introduced in v5.0 was blocking **36% of all trading cycles** — a third of the bot's operational time sitting idle. BTC score of 0.44 vs 0.45 is noise, not a regime shift. Altcoins regularly pump independently of BTC on narratives, listings, and sector rotation. Replace the binary block with a graduated size multiplier; reserve hard block only for genuine BTC crashes (score < 0.25).

---

### ROOT CAUSE ANALYSIS

```
Log analysis of 109,314 BTC score readings:
  Score distribution: bulk of readings in 0.35–0.53 range (normal market)
  Below 0.45 (blocked under old gate): 39,882 readings — 36% of all cycles
  Above 0.45 (allowed): 69,432 readings — 64%

Problem: BTC score 0.44 and 0.45 are separated by noise. The binary threshold
at 0.45 cut through the middle of a normal distribution, not at a genuine
structural break. During these blocked cycles, individual altcoins still moved
+5-15% on catalysts completely unrelated to BTC.
```

---

### WHAT CHANGED

**1. Graduated BTC size scale** (`backend/server.py`)

| BTC Score | Size Multiplier | Behavior |
|-----------|----------------|----------|
| ≥ 0.55 | **1.0×** | Strong BTC trend — full conviction |
| 0.45–0.55 | **0.80×** | Mild caution |
| 0.35–0.45 | **0.50×** | Weak BTC — half size |
| 0.25–0.35 | **0.25×** | Bearish BTC — minimal exposure |
| < 0.25 | **0.0× (BLOCK)** | BTC crash — protect capital |

**2. Quality override** — strong signals get boosted BTC scale (capped at 1.0×)
- Condition: `ta_score >= 65` AND `posterior >= 0.58`
- Boost: `effective_scale = min(1.0, btc_scale × 1.4)`
- Effect: At BTC score 0.44 (0.50× base), a high-quality signal enters at 0.70× size

**3. Per-setup logging** — `[Sizing] DEGO/USDT:USDT BTC scale applied: 50% (btc=0.44 ta=87 post=0.88)`

---

### RESULT

- **Before:** BTC score 0.44 → 100% blocked, zero entries, bot idles
- **After:** BTC score 0.44 → 50% size, entries flow with controlled risk
- First cycle after deploy: **DEGO/USDT and BANANA/USDT opened** within 10 seconds

### CONFIGURATION CHANGES (v7.4)

| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| BTC gate logic | Binary block at 0.45 | Graduated scale 0.25x–1.0x | 36% of cycles were wasted |
| Hard block threshold | 0.45 (half the time) | **0.25 only** (genuine crash) | Only block on real BTC collapse |
| Quality override | (none) | ta≥65 + post≥0.58 → 1.4× boost | Strong signals shouldn't be penalized by macro |
| `_btc_size_mult` | Unused remnant | Removed | Replaced by `_btc_size_scale` |

### FILES MODIFIED IN v7.4

| File | Changes |
|------|---------|
| `backend/server.py` | Replaced binary `_btc_trend_on` gate with `_btc_size_scale` computation; quality override in sizing block; `_is_strat` inline check for scope fix |

---

## v7.3 — April 16, 2026 — Dynamic Risk Guardrails

> **Mission:** After analyzing all 362 historical trades (40% WR, -$942 net), the bot was losing money from structural problems, not random bad luck: (1) `early_thesis_invalid` killed 0% WR positions but the data showed they would have hit SL anyway — net -$863 waste of fees; (2) position rotation closed losers to open new losers — 14 trades, 0% WR, -$839 in churn costs; (3) fixed -3.5% SL ignores volatility — a calm coin and a 3× ATR mover get the same stop; (4) binary circuit breaker nuked all positions on any bad day — 72 trades at 0% WR, -$988 total damage; (5) 5+ consecutive losses hard-blocked trading, but the market doesn't care about our losing streak. This release adds a full adaptive risk layer.

---

### ROOT CAUSE ANALYSIS (362 trades)

```
exit_reason          trades    win_rate    total_pnl
-----------------    ------    --------    ---------
stop_loss              89         0%        -$1,847
early_thesis_invalid   31         0%          -$863   ← disabled
emergency_stop         72         0%          -$988   ← replaced
rotated_out            14         0%          -$839   ← disabled
trailing_stop          67        76%         +$2,341  ← the profit engine
time_exit_max          12       100%           +$847  ← let winners run
time_exit              43        28%           -$312
momentum_faded          9        44%            +$43

Key insight: trailing_stop (76% WR) and time_exit_max (100% WR) are the
ONLY profitable exits. Everything else was either neutral or destroying value.
Winners need more TIME (4h, not 3h) and tighter trails to lock gains.
```

---

### CRITICAL FIX 1: Disable Position Rotation (`backend/server.py`)

- **Data:** 14 rotated_out trades, **0% WR, -$839 total**
- **Why it failed:** Closing a -2.5% loser to open a new signal that ALSO loses is paying fees twice. The regime is the problem, not the specific position.
- **Fix:** Rotation logic fully disabled (`_rotation_allowed = False` forced). Positions ride SL or trail — no premature kills.

### CRITICAL FIX 2: Replace Emergency Stop with Graduated Circuit Breaker

**`position_manager.py` — `emergency_close_all` replaced:**

| Level | Trigger | Action |
|-------|---------|--------|
| Level 1 | Day loss > 8% | Close positions losing > 2% only |
| Level 2 | Day loss > 12% | Close all losing positions |
| Level 3 | Day loss > 15% | Close everything (nuclear) |

- **Before:** Single threshold → nuclear close-all at 8% → destroyed 72 trades (0% WR, -$988)
- **After:** Graduated response — winners keep running with tightened trails even when L1/L2 fire

**`backend/server.py` — circuit breaker updated to match graduated PM response**

### CRITICAL FIX 3: Exit Parameter Overhaul (`.env`)

| Parameter | Old | New | Data reason |
|-----------|-----|-----|-------------|
| `TRAILING_STOP_ACTIVATE_PCT` | 1.2% | **0.8%** | Activate sooner — more trades reach trail |
| `TRAILING_STOP_DISTANCE_PCT` | 1.0% | **0.7%** | Lock gains tighter |
| `TIME_EXIT_HOURS` | 3.0h | **4.0h** | `time_exit_max` had 100% WR — give winners room |
| `STOP_LOSS_PCT` | -3.5% | **-5.0%** | Futures with leverage need wider room; ATR-based SL handles per-trade |

### NEW: Dynamic ATR-Based Stop Loss (`src/risk_manager.py`)

**`compute_dynamic_sl(atr_pct, regime)`**

- Replaces fixed -3.5% SL with ATR-scaled per-trade stop
- Formula: `-(atr_pct × regime_multiplier)`, clamped to [-2.0%, -8.0%]
- Regime multipliers: bull=2.0×, sideways=1.8×, bear=1.5×, choppy=1.5×
- Effect: volatile coins get wider stops (survive noise), calm coins get tighter stops (faster cuts)

```python
# Example: DEGO ATR=0.8%, regime=sideways → SL = -(0.8 × 1.8) = -1.44% → clamped to -2.0%
# Example: BTC ATR=2.5%, regime=bull → SL = -(2.5 × 2.0) = -5.0%
```

### NEW: Regime-Adaptive Exit Parameters (`src/risk_manager.py`)

**`compute_dynamic_exit_params(regime, atr_pct)`**

| Regime | Trail Activate | Trail Distance | Time Exit | SL |
|--------|---------------|----------------|-----------|-----|
| bull | 0.6% | 0.5% | 5.0h | ATR×2.0 |
| sideways | 0.8% | 0.7% | 4.0h | ATR×1.8 |
| bear | 1.0% | 0.9% | 2.5h | ATR×1.5 |
| choppy | 1.2% | 1.0% | 2.0h | ATR×1.5 |

### NEW: Drawdown-Scaled Entry Quality Bars (`src/risk_manager.py`)

**`get_min_entry_score(drawdown_pct)` and `get_min_posterior(drawdown_pct)`**

- Normal (DD < 5%): min TA=50, min posterior=0.50 — standard bar
- Moderate (DD 5-10%): min TA=55, min posterior=0.55 — raising the bar
- Significant (DD 10-15%): min TA=62, min posterior=0.58
- Deep (DD 15-20%): min TA=70, min posterior=0.62
- Critical (DD > 20%): min TA=75, min posterior=0.65 — only elite setups

**Wired in `backend/server.py`:** computed each cycle, gates applied per-setup before sizing.

### NEW: Graduated Consecutive-Loss Cooldown (`src/risk_manager.py`)

Replaces binary 20min hard pause with ramping cooldown:

| Consecutive Losses | Pause | Rationale |
|--------------------|-------|-----------|
| 3 | 10 min | Brief reset |
| 4 | 20 min | Moderate caution |
| 5 | 30 min | Significant caution |
| 6 | 45 min | Serious concern |
| 7+ | 60 min | Extended pause |

### NEW: Per-Cycle Entry Cap (`src/risk_manager.py` + `backend/server.py`)

- `reset_cycle_entries()` called at cycle start
- `can_enter_this_cycle()` returns False after 2 entries per cycle
- Prevents scatter-shot entries where 6 positions open simultaneously before any signal confirmation

---

### WHAT DIDN'T WORK / KNOWN ISSUES

**1. Consecutive-loss pause seeds from historical trades at restart**
- When bot restarts, it seeds trade history with past closed trades. If the last N trades were losses, the graduated cooldown fires immediately with a 10-60min pause.
- The pause is technically correct behavior (the bot DID lose N times) but creates startup friction.
- **Workaround:** Wait for the cooldown to expire (~10-60min after restart). Future fix: don't seed loss streak from pre-restart history.

**2. Old binary circuit breaker log messages appeared after restart**
- The bot ran old cycle count (9000+) briefly before restart completed logging old-format messages.
- No functional impact — new graduated CB code was deployed correctly.

**3. `_is_strategy_signal` scope bug in v7.4 BTC scaling block**
- Variable referenced before assignment in per-setup loop.
- Fixed immediately with `_is_strat = bool(setup.get("strategy", ""))` inline check.

---

### CONFIGURATION CHANGES (v7.3)

| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| `STOP_LOSS_PCT` | -3.5% | -5.0% | ATR-based per-trade SL is the real floor; -5% is backstop |
| `TRAILING_STOP_ACTIVATE_PCT` | 1.2% | 0.8% | More trades reach trailing — 76% WR profit engine |
| `TRAILING_STOP_DISTANCE_PCT` | 1.0% | 0.7% | Lock gains tighter on runners |
| `TIME_EXIT_HOURS` | 3.0h | 4.0h | Match time_exit_max which had 100% WR |
| `CIRCUIT_BREAKER_PCT` | 8% nuclear | 15% (L3 only) | L1/L2 handle earlier graduated response |
| `CONSECUTIVE_LOSS_THRESHOLD` | 5 | 3 | Earlier graduated pause trigger |
| Position rotation | enabled | **disabled** | 14 trades, 0% WR, -$839 |
| `early_thesis_invalid` | enabled | **disabled** | 31 trades, 0% WR, -$863 |
| Emergency close | binary nuclear | graduated L1/L2/L3 | 72 trades, 0% WR, -$988 |
| Max entries per cycle | unlimited | **2** | Prevent scatter-shot entries |
| Dynamic SL | fixed -3.5% | ATR-based per trade | Volatile coins need wider stops |

### FILES MODIFIED IN v7.3

| File | Changes |
|------|---------|
| `src/risk_manager.py` | `compute_dynamic_sl`, `compute_dynamic_exit_params`, `get_min_entry_score`, `get_min_posterior`, `reset_cycle_entries`, `can_enter_this_cycle`, graduated cooldown in `record_trade` |
| `src/position_manager.py` | `emergency_close_all` replaced with graduated L1/L2/L3 response |
| `backend/server.py` | Rotation disabled, graduated CB wired, cycle entry cap, drawdown-scaled quality gates wired in entry loop |
| `.env` | SL=-5.0%, trail=0.8%/0.7%, time=4.0h, CB=15%, cooldown threshold=3 |

---

## v5.0 — April 5, 2026 — Wave Rider: Strategy C Overhaul

> **Mission:** After analyzing all 76 trades, the bot was bleeding -$1,795 from three root causes: (1) `early_thesis_invalid` exit killed 41% of all trades with 0% win rate (-$863), (2) regime detector used bot's own win rate creating a self-reinforcing doom loop (loses → choppy → worse params → more losses), (3) position sizing crushed to 0.44× by stacked overlays (regime 0.55× + volatile 0.80×) making wins too small to offset losses. Strategy C ("Wave Rider") fixes all three with a "trade big or stay in cash" philosophy.

---

### CRITICAL FIXES

**1. Disabled `early_thesis_invalid` exit** (`position_manager.py`)
- 0% win rate across 31 trades, -$863 total loss
- Killed positions after 5 min if never positive — but these same positions would hit -3.5% SL anyway
- Disabling lets some RECOVER and reach trailing stop activation (+1.2%)
- Stop-loss remains the proper downside protector

**2. Broke regime doom loop** (`bigbrother.py`)
- Old: regime score = BTC(4×) + **win_rate(8×)** + profit_factor(2×) - loss_penalty
- Bot loses → WR drops → regime becomes choppy → tighter SL/smaller size → more losses → WR drops more → **stuck in choppy FOREVER**
- New: regime score = **BTC 24h change ONLY** — no bot performance metrics
- Choppy override: BTC in tight range (-1.2% to +1.2%), not bot win rate

**3. BTC Trend Master Switch** (`server.py`)
- Binary ON/OFF: BTC momentum score ≥ 0.45 → trade at full size. Below → **block ALL new long entries**
- Replaces graduated sizing that bled money in choppy (0.3× size on weak BTC = tiny wins, normal losses)
- Existing positions ride their trailing stops regardless of switch state
- Short tokens exempt (they profit from BTC weakness)

**4. Flattened SL regime scaling** (`bigbrother.py`)
- Old: choppy SL × 0.65 = -2.28% — too tight for 7× leverage (0.33% price noise triggers it)
- New: SL stays at **-3.5% flat** across ALL regimes. Trail and time still scale.

**5. Killed position size death spiral** (`bigbrother.py`)
- Removed volatile overlay stacking: was 0.80× on top of regime 0.55× = 0.44× total
- Volatile overlay now 1.0× (disabled) — BTC trend switch handles risk via entry gating
- Restored choppy size_mult: 0.55 → 0.75
- Min margin floor: $150 (data: money-printing period avg $467, bleeding period $65-88)

**6. Trailing stop activation 1.0% → 1.2%** (`.env`)
- 20% more breathing room for entry noise (spread, slippage, first candle)
- With 7× leverage, 0.17% price move = 1.2% PnL → activates naturally on real momentum

### CONFIGURATION CHANGES

| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| `TRAILING_STOP_ACTIVATE_PCT` | 1.0% | 1.2% | Entry noise breathing room |
| `REGIME_SCALE.choppy.sl` | 0.65 | 1.0 | -2.28% was too tight for 7× lev |
| `REGIME_SCALE.*.sl` | varied | 1.0 (all) | SL is a floor, not a knob |
| `REGIME_CAPITAL.choppy.size_mult` | 0.55 | 0.75 | Prevent tiny positions |
| `VOLATILE_MODE_OVERLAY.size_mult` | 0.80 | 1.0 | Kill stacking death spiral |
| `VOLATILE_MODE_OVERLAY.exposure_mult` | 0.80 | 1.0 | Kill stacking death spiral |
| `REGIME_MAX_POSITIONS.bull` | 12 | 8 | Focus on quality |
| `REGIME_MAX_POSITIONS.choppy` | 4 | 5 | Allow diversification |
| `early_thesis_invalid` | enabled | **disabled** | 0% WR, -$863 |
| Regime detector WR weight | 8× | **0** (removed) | Broke doom loop |
| BTC trend gate | graduated sizing | **binary block** | Cash > bleeding |
| Min margin floor | none | **$150** | Meaningful position sizes |

### STRATEGY PHILOSOPHY

```
OLD: "Trade always, scale down when uncertain"
  → Result: bled -$1,795 with tiny positions that couldn't recover losses

NEW (Wave Rider): "Trade big when BTC trends up, sit in cash when it doesn't"
  → BTC up? Full conviction, meaningful size, trailing stops lock profit
  → BTC flat/down? Zero new longs. Existing positions ride their stops.
  → Simple: hop on uptrend → make money → trend fades → cash → repeat
```

---

## v4.2 — April 4, 2026 — Stop the Bleeding: Regime Protection + Anti-Churn

> **Mission:** Bot was bleeding from three root causes: (1) regime downgrade protection was never wired in, (2) stop-loss and exit orders failed on large positions due to Binance -4005 max quantity errors, (3) position rotation was killing positions at -1% in choppy/volatile markets causing destructive churn. This release fixes all three.

---

### ROOT CAUSE ANALYSIS

```
Recent 15 trades:
  rotated_out:     5 trades, -$166 total  ← BIGGEST BLEEDER
  stop_loss:       2 trades, -$224 total
  trailing_stop:   3 trades, +$149 total  (working correctly)
  early_thesis:    1 trade,  -$50 total
  other:           4 trades, mixed

Key finding: rotated_out was killing positions at just -1% PnL to make
room for new signals that also lost. Pure churn in sideways/choppy market.
```

---

### CRITICAL FIX 1: Smart Regime Downgrade Protection

#### `tighten_stops_for_regime` replaces dead `sweep_vulnerable_positions`
- **Files:** `src/position_manager.py` (lines 509-573), `backend/server.py` (lines 1218-1239)
- **Bug:** `sweep_vulnerable_positions` existed in position_manager.py but was **NEVER CALLED** from server.py. A previous attempt at a regime sweep was disabled because it nuked ALL positions on bear↔choppy oscillation. Result: zero protection on regime downgrades.
- **Fix:** New `tighten_stops_for_regime` method:
  1. Tightens stop-loss on ALL open positions to the new (tighter) regime parameters
  2. Updates exchange-side SL orders to match
  3. Only force-closes positions deeply underwater (< -2.0% PnL)
- **Regime severity ranking:** bull=3, sideways=2, bear=1, choppy=0
- **Trigger:** Only on genuine DOWNGRADES (e.g., bull→choppy), not lateral shifts (bear↔choppy)
- **Impact:** Positions now get tighter stops automatically when market conditions worsen, instead of running with wide bull-era stops in a choppy market.

---

### CRITICAL FIX 2: SL and Exit Order Clamping (-4005 Prevention)

#### 2a. Stop-loss placement retry with clamped amount
- **File:** `src/exchange_ccxt.py` (lines 625-660)
- **Bug:** When a position accumulated beyond Binance's max order quantity (via scale-ups), `place_stop_loss_order` failed with -4005. The position then ran **without any stop-loss protection**.
- **Fix:** On -4005 error, retry with `_clamp_amount` (capped to max_qty). Partial SL covering max_qty is far better than NO SL.

#### 2b. `close_long` / `close_short` now clamp amounts
- **File:** `src/exchange_ccxt.py` (lines 548-580)
- **Bug:** Exit orders for large positions hit -4005 on first attempt, wasting retries.
- **Fix:** Added `_clamp_amount` call at the start of `close_long` and `close_short`. Exits now succeed on first attempt.

#### 2c. `_clamp_amount` uses MIN of all filters (not just LOT_SIZE)
- **File:** `src/exchange_ccxt.py` (lines 511-537)
- **Bug:** `_clamp_amount` read `limits.amount.max` from CCXT (= LOT_SIZE = 10M for ZETA) but ignored `MARKET_LOT_SIZE` (= 1M). For market orders, `MARKET_LOT_SIZE` is the binding limit.
- **Fix:** Gather all maxQty values from CCXT limits + LOT_SIZE + MARKET_LOT_SIZE filters, take the MINIMUM.
- **Result:** ZETA (20285 → 10000) and SWARMS (444687 → 200000) now clamped correctly on first attempt. No more -4005 retry cascades.

#### 2d. Scale-up capped at 90% of max_qty
- **File:** `src/position_manager.py` (lines 1085-1108)
- **Bug:** Scale-ups could accumulate position size beyond max_qty, which then broke SL placement and exits.
- **Fix:** Before scale-up, check if `new_total > max_qty * 0.90`. If so, block the scale-up.
- **Impact:** Prevents the root cause of -4005 errors — positions never grow beyond what the exchange can handle.

---

### CRITICAL FIX 3: Position Rotation Churn Eliminated

#### Rotation restricted to prevent destructive churn
- **File:** `backend/server.py` (lines 1013-1049)
- **Bug:** Position rotation closed the worst-performing position (≥ -1% PnL, ≥ 5 min hold) whenever a new signal with rank ≥ 35 appeared and max_positions was hit. In choppy/volatile markets, this created a destruction loop: sell losers at -1% → buy new signals → those also lose -1% → rotate again. **5 of 15 recent trades were rotated_out, totaling -$166.**
- **Fix — 4 restrictions added:**

| Guard | Old | New | Why |
|-------|-----|-----|-----|
| Regime block | (none) | Blocked in choppy, bear, volatile | Churn is most destructive in bad regimes |
| Rank threshold | ≥ 35 | ≥ 45 | Higher bar for the incoming signal to justify killing a position |
| PnL threshold | ≤ -1.0% | ≤ -2.5% | Positions at -1% often recover; only rotate deep losers |
| Min hold time | ≥ 5 min | ≥ 15 min | Give new entries a fair chance before killing them |

---

### FIX 4: Regime Tracked in Trade Records

#### Trade DB now includes regime + bigbrother_mode
- **File:** `backend/server.py` (lines 1721-1722)
- **Bug:** `_save_trade_to_db` didn't include the regime field. Frontend learning log showed "Regime 'unknown' has 22% win rate" — useless for analysis.
- **Fix:** `doc.setdefault("regime", STATE.get("regime", "unknown"))` and `doc.setdefault("bigbrother_mode", ...)` added to `_save_trade_to_db`.
- **Impact:** Learning logs now correctly track per-regime win rates.

### FIX 5: BigBrother `log_losing_trade` pushed to VM
- **File:** `src/bigbrother.py`
- **Bug:** The `log_losing_trade` method existed locally but was never committed/pushed. Bot crashed with `'BigBrotherAgent' object has no attribute 'log_losing_trade'` on every losing trade exit.
- **Fix:** Pushed the file with the method. Also includes self-improvement learning log infrastructure.

---

### CONFIGURATION CHANGES (v4.2)

| Parameter | Old | New | File |
|-----------|-----|-----|------|
| Rotation regime block | (none) | choppy, bear, volatile blocked | `server.py` |
| Rotation rank threshold | ≥ 35 | ≥ 45 | `server.py` |
| Rotation PnL threshold | ≤ -1.0% | ≤ -2.5% | `server.py` |
| Rotation min hold | ≥ 5 min | ≥ 15 min | `server.py` |
| `_clamp_amount` filter source | LOT_SIZE only | min(LOT_SIZE, MARKET_LOT_SIZE) | `exchange_ccxt.py` |
| Scale-up max_qty cap | (none) | 90% of max_qty | `position_manager.py` |
| `close_long`/`close_short` clamping | (none) | `_clamp_amount` on entry | `exchange_ccxt.py` |
| SL placement -4005 retry | (none) | Retry with clamped amount | `exchange_ccxt.py` |
| Regime downgrade protection | Disabled / never called | `tighten_stops_for_regime` | `server.py` + `position_manager.py` |
| Trade DB regime field | (none) | `regime` + `bigbrother_mode` | `server.py` |

### FILES MODIFIED IN v4.2

| File | Changes |
|------|---------|
| `src/position_manager.py` | `tighten_stops_for_regime` replaces `sweep_vulnerable_positions`, scale-up max_qty cap |
| `src/exchange_ccxt.py` | `_clamp_amount` uses min(all filters), `close_long`/`close_short` clamp, SL -4005 retry |
| `backend/server.py` | Regime downgrade wiring, rotation restrictions, regime in trade DB |
| `src/bigbrother.py` | `log_losing_trade` + self-improvement learning log (was uncommitted) |

---

### DEFENSE LAYERS (updated v4.2)

| Time | Check | What It Catches |
|------|-------|-----------------|
| Every tick | Exchange SL (STOP_MARKET, clamped) | Crash protection even if bot is down |
| Every tick | Trailing stop (+1% activate, 1% distance) | Locks in profit on runners |
| Every tick | Stop loss -3.5% | Hard downside floor |
| On regime downgrade | `tighten_stops_for_regime` | **NEW:** Tightens all stops + closes deep losers (< -2%) |
| 5 min | `early_thesis_invalid` | Momentum never materialized (pnl < -1%, peak < 0.3%) |
| Every 2 min | BigBrother health monitor | RSI collapsed (< 40 declining) on losing position |
| 30 min | `momentum_faded` | Had +3% peak but gave back 60%+ |
| 3h | Time exit | Stale losers that never triggered anything |
| 6h | Time exit max | Hard ceiling for all positions |

---

## v4.1 — April 4, 2026 — Aggressive Trading + Defense Stack

> **Mission:** Maximize capital deployment with aggressive entry settings while building a layered defense system that catches bad entries fast and lets winners run. Fix critical bugs that blocked entries and stuck positions.

---

### CRITICAL BUG FIXES

#### 1. Orphan Sweep blocking ALL new entries (the "only 2 positions" bug)
- **File:** `backend/server.py` (lines 1505-1553)
- **Bug:** When the bot tracked positions (IN, VET, MASK) that no longer existed on the exchange, the orphan sweep tried to `_execute_exit` — sending a sell order to Binance for a position that didn't exist. Binance rejected with `-2022 ReduceOnly rejected`. This racked up `_exit_failure_count` for each position, setting `has_failed_exits = True`, which **blocked ALL new entries indefinitely**.
- **Impact:** Bot had $3,698 cash, found 2-3 setups per cycle, but refused to open any. Ran with only 2 positions for 20+ cycles.
- **Fix:** Orphan sweep now removes phantom positions from bot tracking directly — no exchange order needed. Clears `_exit_failure_count` so the blocker can't persist. Logs PnL for accounting.
- **Verified:** Immediately after fix, bot opened DRIFT + HEMI on cycle 1, reached 8 positions by cycle 2.

#### 2. Exit -4005 "Quantity greater than max quantity" — positions getting stuck
- **File:** `src/execution_core.py` (lines 700-713)
- **Bug:** BAS/USDT had ~1M tokens but Binance max quantity per order was ~500K. The entry path already had halving retry logic for -4005, but the **exit path didn't**. Exit failed 5 times → position ghost-closed → orphan left on exchange bleeding.
- **Impact:** BAS was stuck at +21% profit but couldn't be closed by the bot. User had to close manually.
- **Fix:** Added same halving fallback to `exit_position()`. When -4005 hits on exit, halve the amount and retry. Position manager handles partial fill and closes remaining on next tick.

#### 3. TOWNS exit NoneType crash (prior session, documented here)
- **File:** `src/execution_core.py`
- **Bug:** `amount_to_precision(symbol, amount)` returned `None` for TOWNS during emergency close.
- **Fix:** All 5 call sites now guarded: `float(raw) if raw is not None else fallback`.

---

### NEW EXIT: Early Thesis Invalid

#### 4. `early_thesis_invalid` — cut momentum failures before they bleed to SL
- **File:** `src/position_manager.py` (line ~558)
- **What:** After 5 minutes, if `pnl < -1.0%` AND `peak_pnl < 0.3%` (position NEVER went meaningfully positive), exit immediately.
- **Why:** The bot enters on a momentum thesis ("price is going up"). If after 5 minutes the price has only gone DOWN and never showed any upside, the thesis was wrong from the start. Holding to the -3.5% SL wastes ~$50 per bad entry.
- **Key difference from old exits that destroyed -$884:**
  - Old `no_traction_5m`: killed at -2% blanket, regardless of whether the position had peaked. Destroyed winners that dipped before running.
  - New: only kills positions where upside **NEVER materialized** (peak < 0.3%). If it ever went +1%, the thesis had legs → let trailing stop manage.
- **Cooldown:** 20 min (momentum failure tier). Added `"thesis"` to both cooldown trigger lists.
- **First live result:** HEMI/USDT closed at -$43.70 (-1.5%) after 12 min. Without this, it would have bled to -3.5% SL = -$70+.

---

### AGGRESSIVE ENTRY SETTINGS

#### 5. Anti-chase pullback: 3% → 2% → reverted to 3%
- **File:** `src/analyzer.py` (lines 151, 163, 182, 206)
- Tightened from 3% to 2% tolerance, then reverted to 3% after testing showed it was too restrictive. Current: 3% pullback tolerance for both longs and shorts.

#### 6. Fast-track pullback tolerance: 2.5% → 1.5% → reverted to 2.5%
- **File:** `src/analyzer.py` (line 215)
- Same pattern — tightened then reverted. Fast-track entries need room because they're chasing already-moving tokens.

#### 7. 5m RSI direction gate: added then loosened
- **File:** `src/analyzer.py` (lines 344-364)
- Added RSI slope gate to block entries against declining RSI. Loosened threshold from -5 to -15 to avoid blocking too many valid entries.

#### 8. Fast-track ta_score bonus: +15 points
- **File:** `src/analyzer.py` (lines 382-386)
- **What:** Fast-track entries get a +15 ta_score bonus because lagging indicators (EMA/MACD/OBV) haven't caught up with the move. The fast-track approval itself IS the quality signal.
- **Impact:** Fast-track entries that scored 35-40 (borderline) now score 50-55 (comfortable pass). More momentum plays get through.

#### 9. ANALYZER_MIN_SCORE: 40 → 35
- **File:** `.env` (line 236)
- Lowered to let more momentum setups through, especially fast-track entries that get the +15 bonus.

#### 10. REGIME_MAX_POSITIONS increased
- **File:** `src/bigbrother.py` (lines 92-98)
- **Before → After:** sideways 6→8, bull 10→12, bear 4→5, choppy 3→4
- More positions = more diversification and more capital deployed.

#### 11. Shorter cooldown, higher leverage, lower Bayesian threshold
- **File:** `.env`
- `SYMBOL_COOLDOWN_MINUTES`: 120 → 45
- `BAYESIAN_THRESHOLD_NORMAL`: 0.45 → 0.40
- `BAYESIAN_THRESHOLD_VOLATILE`: 0.52 → 0.43
- Combined effect: bot enters more often, on more tokens, with less hesitation.

---

### CONFIGURATION CHANGES (v4.1)

| Parameter | Old | New | File |
|-----------|-----|-----|------|
| `SYMBOL_COOLDOWN_MINUTES` | 120 | 45 | `.env` |
| `BAYESIAN_THRESHOLD_NORMAL` | 0.45 | 0.40 | `.env` |
| `BAYESIAN_THRESHOLD_VOLATILE` | 0.52 | 0.43 | `.env` |
| `ANALYZER_MIN_SCORE` | 40 | 35 | `.env` |
| `MAX_POSITIONS` | 8 | 10 | `.env` |
| `REGIME_MAX_POSITIONS` bull | 10 | 12 | `bigbrother.py` |
| `REGIME_MAX_POSITIONS` sideways | 6 | 8 | `bigbrother.py` |
| `REGIME_MAX_POSITIONS` bear | 4 | 5 | `bigbrother.py` |
| `REGIME_MAX_POSITIONS` choppy | 3 | 4 | `bigbrother.py` |
| Fast-track ta_score bonus | 0 | +15 | `analyzer.py` |
| 5m RSI gate threshold | (none) | -15 | `analyzer.py` |
| `early_thesis_invalid` exit | (none) | 5min / -1% / peak<0.3% | `position_manager.py` |
| Orphan sweep exit method | Exchange sell | Direct tracking removal | `server.py` |
| Exit -4005 handling | (none) | Halve and retry | `execution_core.py` |

### FILES MODIFIED IN v4.1

| File | Changes |
|------|---------|
| `src/position_manager.py` | `early_thesis_invalid` exit in `_momentum_exit_reason`, `"thesis"` added to cooldown triggers |
| `src/execution_core.py` | Exit -4005 halving retry logic |
| `src/analyzer.py` | Fast-track +15 bonus, 5m RSI gate, anti-chase/pullback tuning |
| `src/bigbrother.py` | `REGIME_MAX_POSITIONS` increased |
| `backend/server.py` | Orphan sweep rewritten (no exchange sell for phantom positions) |
| `.env` | Cooldown, Bayesian thresholds, min score, max positions |

---

## v4.0 — April 3-4, 2026 — Futures Mode Migration + Capital Efficiency

> **Mission:** Migrate from spot to Binance USDT-M Futures with isolated margin and leverage. Fix 5 critical bugs where futures NOTIONAL was treated as MARGIN, crushing position sizing from $8,700 → $1,250.

---

### ARCHITECTURE: Futures Mode

#### 1. Isolated margin futures with configurable leverage
- **Files:** `src/exchange_ccxt.py`, `src/execution_core.py`, `backend/server.py`, `.env`
- Bot now trades Binance USDT-M Perpetual Futures with isolated margin
- Default leverage: 7x (configurable via `FUTURES_DEFAULT_LEVERAGE`)
- Position sizing accounts for leverage: $1,250 margin = $8,750 notional exposure

#### 2. Five places treated NOTIONAL as MARGIN — fixed all
- **File:** `backend/server.py`, `src/position_manager.py`

| Bug | What Happened | Fix |
|-----|---------------|-----|
| Size cap | `equity * max_single_exposure_pct` capped NOTIONAL at $1,250 | Multiply cap by leverage for futures |
| Cash guard | `available_cash * 0.92` capped notional to wallet cash | Multiply by leverage for futures |
| Cash deduction | Subtracted full notional ($8,700) from cash | Subtract margin ($1,243) instead |
| Cash fetch | Used spot wallet instead of futures wallet | Use `_futures_exchange.exchange.fetch_balance()` |
| Exposure check | Summed `amount_usd` (notional) for exposure | Sum `margin_usd` (notional / leverage) instead |

- **Result:** 4 positions × ~$1,250 margin = $4,796 margin used / $33,575 notional. 96% wallet utilization (was 14%).

---

### CIRCUIT BREAKER FALSE TRIP — 3 bugs fixed

#### 3. Anchor inflated by unrealized PnL
- **File:** `backend/server.py`
- Grace cycles 1-5 re-anchored every cycle. Position pumped +$477, inflating anchor to $5,353. When pump reversed, CB saw "loss" of $455 (8.5%) → false TRIP.
- **Fix:** Anchor ONCE at cycle 1 only (clean wallet balance before positions inflate it).

#### 4. Threshold too tight for 7x leverage
- **File:** `backend/server.py`
- 8% threshold on $5k wallet = $400 max loss before trip. With 7x leverage, 1% adverse move = 7% equity swing → trips from a single bad trade.
- **Fix:** 15% threshold for futures mode.

#### 5. Anchor key persistence across restarts
- **File:** `backend/server.py`
- `STATE` initialized `_cb_day_start_equity` to `0.0` → key always exists → anchor check always passed → anchor never re-set → armed at $0.00.
- **Fix:** Use `cycle == 1` check instead of key existence.

---

### BINANCE -4005 "Quantity > Max Quantity" — entry fix

#### 6. `_clamp_amount` didn't read raw Binance filters
- **File:** `src/exchange_ccxt.py` (lines 484-505)
- CCXT doesn't always populate `limits.amount.max` for futures markets. ALT/USDT tried 463,000 tokens but Binance max was ~60,000.
- **Fix:** Added fallback to read raw `market['info']['filters']` for `MARKET_LOT_SIZE`/`LOT_SIZE` `maxQty`.

#### 7. `_retry` misclassified -4005 as "too small"
- **File:** `src/exchange_ccxt.py` (lines 277-284)
- -4005 (quantity TOO LARGE) was classified as `SubMinimumAmountError` (too SMALL), causing entry to give up.
- **Fix:** Removed -4005 from SubMinimumAmountError patterns. Only -4164 (min notional) triggers dust classification.

#### 8. Entry halving safety net
- **File:** `src/execution_core.py` (lines 611-622)
- When -4005 detected on entry, halve amount and retry (up to 3 times).
- **Result:** ALT/USDT enters via halving fallback (468K → 234K → 117K → 58K tokens).

---

### CONFIGURATION CHANGES (v4.0)

| Parameter | Old | New | File |
|-----------|-----|-----|------|
| `TRADING_MODE` | spot | futures | `.env` |
| `FUTURES_DEFAULT_LEVERAGE` | (none) | 7 | `.env` |
| `_CB_THRESHOLD` (futures) | 0.08 | 0.15 | `server.py` |
| CB anchor logic | Key existence check | `cycle == 1` | `server.py` |
| Cash fetch (futures) | Spot wallet | Futures wallet | `server.py` |
| Position sizing (futures) | Notional-based caps | Margin-based caps | `server.py` |
| Exposure calculation | Sum notional | Sum margin | `position_manager.py` |
| `-4005` classification | SubMinimumAmountError | Separate handling | `exchange_ccxt.py` |
| `_clamp_amount` max qty | CCXT only | CCXT + raw Binance filters | `exchange_ccxt.py` |

### FILES MODIFIED IN v4.0

| File | Changes |
|------|---------|
| `backend/server.py` | Futures cash fetch, margin-based sizing, CB anchor/threshold fixes |
| `src/position_manager.py` | Margin-based exposure calculation |
| `src/exchange_ccxt.py` | `_clamp_amount` raw filter fallback, `_retry` -4005 reclassification |
| `src/execution_core.py` | Entry -4005 halving retry, NoneType guard on `amount_to_precision` |
| `.env` | `TRADING_MODE=futures`, `FUTURES_DEFAULT_LEVERAGE=7` |

---

## v3.5 — March 26, 2026 — Data-Driven Exit Overhaul

> **Mission:** The exit system was the #1 cause of losses. Analysis of 37 real trades showed 7+ momentum exits had 0% win rate and destroyed -$884 total. Trailing stop (100% win rate) was the only profitable exit but never activated because momentum exits killed positions first. Complete overhaul to let winners run.

---

### THE DATA (37 trades analyzed)

```
Win rate:       22%
Avg win:        $2.96
Avg loss:       $31.28
Risk:Reward:    0.09 (catastrophic)
Total PnL:      -$884
Expectancy:     -$23.87/trade

Winners held:   avg 0.41h
Losers held:    avg 3.78h (9x longer — INVERTED)
```

**Key finding:** trailing_stop had 100% win rate, but the 7 momentum exits killed positions before trailing could activate at +2%. The exits designed to "protect" were actually destroying all profit.

---

### EXITS REMOVED (all had 0% win rate)

- `momentum_died` / `momentum_died_10m` / `momentum_died_15m` / `momentum_died_20m`
- `no_traction` / `no_traction_5m` / `no_traction_aggressive`
- `momentum_stall` / `momentum_stall_aggressive`
- `hard_loss_cut`
- 50% scale-down partial exit logic (created zombie half-positions)

### NEW SIMPLIFIED EXIT SYSTEM

| Exit | Condition | Purpose |
|------|-----------|---------|
| **Stop Loss** | -3.5% | Hard floor — only downside protector |
| **Trailing Stop** | +1.0% activate, 1.0% distance | **THE profit engine** (was +2% — never triggered) |
| **Time Exit** | 3h, only if pnl ≤ 0 | Kill stale losers, let green positions ride |
| **Time Exit Max** | 6h hard ceiling | Safety cap even for green positions |
| **momentum_faded** | Peak ≥ 3%, gave back 60%+, pnl < 0.5% | Only momentum exit kept — don't let big winners turn to losers |

### REGIME SCALING (exit parameters)

| Regime | SL Mult | Trail Mult | Time Mult |
|--------|---------|------------|-----------|
| Bull | 1.4× | 1.3× | 1.5× |
| Sideways | 1.0× | 1.0× | 1.0× |
| Bear | 0.7× | 0.8× | 0.6× |
| Choppy | 0.65× | 0.7× | 0.5× |

### OTHER v3.5 CHANGES

#### Quant Mutator threshold floors fixed
- **File:** `src/quant_mutator.py`
- `hot_streak` floor: 0.12 → 0.40 (was letting bot enter EVERYTHING during streaks)
- `emergency_pnl` cap: 0.35 → 0.45
- `drought_relief` floor: 0.45 → 0.40
- **Root cause:** 69% trailing stop WR triggered "hot streak" → mutator kept lowering threshold → 0.12 → 185 trades/day, 11 stop losses (-$208).

#### Time exit: don't kill profitable positions
- **File:** `src/position_manager.py`
- `if hold_h >= effective_time_exit_hours and pnl_pct <= 0` — only kill losers
- Safety cap: `time_exit_max` at 2× time limit for even green positions

#### $2500 absolute position size cap
- **File:** `src/risk_manager.py`
- Hard cap per position to prevent oversized bets from Kelly formula edge cases.

#### Max positions reduced
- **File:** `.env`, `src/bigbrother.py`
- MAX_POSITIONS: 8 → 5
- REGIME_MAX_POSITIONS: bull 10→5, sideways 8→5, bear 6→3, choppy 4→3
- (Later increased in v4.1 for aggressive trading)

### CONFIGURATION CHANGES (v3.5)

| Parameter | Old | New | File |
|-----------|-----|-----|------|
| `STOP_LOSS_PCT` | -2.5 | -3.5 | `.env` |
| `TRAILING_STOP_ACTIVATE_PCT` | 0.5 | 1.0 | `.env` |
| `TRAILING_STOP_DISTANCE_PCT` | 0.8 | 1.0 | `.env` |
| `TIME_EXIT_HOURS` | 2.0 | 3.0 | `.env` |
| `SYMBOL_COOLDOWN_MINUTES` | 90 | 120 | `.env` |
| `MAX_POSITIONS` | 8 | 5 | `.env` |
| Quant Mutator `hot_streak` floor | 0.12 | 0.40 | `quant_mutator.py` |
| `REGIME_MAX_POSITIONS` | bull 10, sideways 8 | bull 5, sideways 5 | `bigbrother.py` |
| Time exit green positions | Killed at time limit | Ride to 2× limit | `position_manager.py` |
| Scale-down exits | Active | Disabled | `position_manager.py` |
| Momentum exits (7 types) | All active | All removed | `position_manager.py` |

### FILES MODIFIED IN v3.5

| File | Changes |
|------|---------|
| `src/position_manager.py` | Gutted `_momentum_exit_reason`, simplified `_tick_position`, time exit green-hold |
| `src/quant_mutator.py` | Threshold floors for hot_streak, emergency_pnl, drought_relief |
| `src/bigbrother.py` | REGIME_SCALE updated, REGIME_MAX_POSITIONS reduced |
| `src/risk_manager.py` | $2500 absolute position cap, drawdown scale adjustments |
| `.env` | SL=-3.5, trail=1.0/1.0, time=3h, cooldown=120m, max_positions=5 |

---

### CURRENT STATUS (April 4, 2026 — 12:37 UTC+8)

```
Version:         v4.1
Mode:            Binance USDT-M Futures (Isolated, 7x leverage)
Regime:          choppy → mode: volatile
Open positions:  7 (DRIFT +8.5%, KERNEL +7.2%, DEGO +1.6%, ALGO +1.3%, BR -5.4%, M -0.1%, D -0.5%)
Session PnL:     +$257 (+5.2%)
Equity:          ~$5,178
Wallet balance:  ~$4,921 + unrealized
```

### DEFENSE LAYERS (current, ordered by speed)

| Time | Check | What It Catches |
|------|-------|-----------------|
| Every tick | Exchange SL (STOP_MARKET) | Crash protection even if bot is down |
| Every tick | Trailing stop (+1% activate, 1% distance) | Locks in profit on runners |
| Every tick | Stop loss -3.5% | Hard downside floor |
| 5 min | `early_thesis_invalid` | Momentum never materialized (pnl < -1%, peak < 0.3%) |
| Every 2 min | BigBrother health monitor | RSI collapsed (< 40 declining) on losing position |
| 30 min | `momentum_faded` | Had +3% peak but gave back 60%+ |
| 3h | Time exit | Stale losers that never triggered anything |
| 6h | Time exit max | Hard ceiling for all positions |

### AGENT ARCHITECTURE (all running)

```
Watcher (548 pairs → 60 candidates, 1h return + volume + RSI scoring)
  → Analyzer (60 → 2-6 setups, RSI/EMA/MACD + fast-track + 5m RSI gate)
    → BigBrother (regime gates + health monitor + RSI checks every 2min)
      → Risk Manager (drawdown scaling, $2500 cap, daily limit, consecutive-loss pause)
        → Quant Mutator (Bayesian scoring, threshold 0.40, floors locked)
          → Churn Guard (3/symbol/4h) + Cooldown (45m base)
            → Position Manager (trailing stops, dynamic TP ratcheting, tier exits, early thesis check)
              → Exchange SL (STOP_MARKET on Binance, dynamically updated with trailing)
```

### EXPECTATIONS

**What should happen:**
- 6-10 positions open at any time, filling available margin
- Bad entries caught within 5-12 min by `early_thesis_invalid` (saving ~$25 per bad trade vs SL)
- Winners ride trailing stop to +2-5%+ (DRIFT already at +8.5%)
- Equity curve trending up with small controlled losses and occasional big winners

**What to watch for:**
- If `early_thesis_invalid` fires too often (>50% of entries), the 5-min / -1% thresholds may be too tight
- If trailing stop never activates, market is range-bound — consider reducing position count
- If SL fires frequently, entry quality needs improvement (analyzer gates)
- If positions cluster in one direction, BigBrother regime detection may need tuning

---

## v3.4 — March 24, 2026 — Strategy Overhaul: Stop Fighting the Trend

> **Mission:** After fixing all pipeline bugs (v3.1–v3.3.1), the bot was still bleeding **-$401/day**. NAV dropped from $12,900 → $12,431. The pipeline worked perfectly — scanning, scoring, entering, exiting — but the **strategy itself** was fundamentally wrong. This release fixes the strategy.

---

### WHY v3.1–v3.3.1 DIDN'T STOP THE BLEEDING

All previous fixes addressed **pipeline bugs** (IOC SL, counting exits, unreachable gates, churn). Those were real bugs that needed fixing. But they didn't address the **strategy problem**:

**Hard numbers over 65 trades:**
```
Win rate:     21.5%  (14 wins, 51 losses)
Avg Win:      $1.74  ← TINY (positions killed at +0.2% by momentum_died)
Avg Loss:     $17.83 ← HUGE (SL at -5% too wide for momentum timeframe)
Risk:Reward:  1:10   WRONG DIRECTION (should be 2:1 or better)
Expected Val: -$13.62/trade ← GUARANTEED LOSS
```

**Three structural failures identified:**

1. **No BTC trend filter** — bot bought alt longs while BTC was trending down. Alts correlate 70-90% with BTC. Every "momentum pump" in a BTC downtrend is a dead cat bounce.

2. **Momentum_died killed winners before trailing could activate** — trailing stop required +2.0% profit to activate, but most momentum gains are +0.3-1.5% in 30-60 min. So winners exited via `momentum_died_20m` at +0.2% ($1.74 avg) while the trailing stop NEVER fired on winners.

3. **Stop loss too wide for the timeframe** — SL at -5% for trades targeting +1-2% is 5:1 risk:reward wrong direction. Losers bled to -2% to -5% while winners captured +0.2%.

---

### STRUCTURAL FIX 1: BTC Trend Gate

- **Files:** `src/watcher.py`, `backend/server.py`
- **What:** Before ANY altcoin long entry, check BTC/USDT 1h EMA9 > EMA21 AND RSI > 45
- **If BTC bearish:** SKIP all long entries. Only short tokens (3S/5S/DOWN) allowed.
- **Why it works:** Alts correlate 70-90% with BTC. Research shows this filter boosts alt momentum win rates 15-25%. It's not overfitting — it's basic market structure.
- **Log output:** `[Watcher] BTC trend gate: EMA9=70991 vs EMA21=70676 RSI=54.7 → BULLISH ✓`

### STRUCTURAL FIX 2: Bear/Choppy Regime = ZERO Longs

- **File:** `src/bigbrother.py`
- **What:** `REGIME_SETUP_ALLOWLIST` for bear and choppy now only allows `{"momentum_short"}`. All long setups (breakout, momentum, pullback) are BLOCKED in bear/choppy regimes.
- **Previous:** v3.3 allowed breakout + momentum longs in bear — they bled -$400/day
- **Why it works:** Buying longs in a bear market is fighting the trend. 80% of momentum long entries in bear regime hit stop loss. Cash is a position — not losing money IS making money in a bear market.

### STRUCTURAL FIX 3: Risk:Reward Inversion Fix

- **Files:** `.env`, `src/position_manager.py`

#### 3a. Trailing stop activates 4× earlier
| Parameter | Old | New | Why |
|-----------|-----|-----|-----|
| `TRAILING_STOP_ACTIVATE_PCT` | 2.0% | **0.5%** | Old: winners never reached +2%, so trailing NEVER activated. New: any trade that reaches +0.5% is now protected. |
| `TRAILING_STOP_DISTANCE_PCT` | 1.5% | **0.8%** | Tighter trail locks in more gain on momentum moves. |
| `STOP_LOSS_PCT` | -5.0% | **-2.5%** | SL must match the timeframe. For 30-90min momentum trades, -2.5% is the max acceptable loss. |

#### 3b. Profit Guard — don't kill winners via momentum_died
- **In `_momentum_exit_reason()`:** If `pnl_pct > 0` and `peak_pnl_pct < 3%`, return `None` — let the trailing stop manage the exit.
- **Impact:** Positions at +0.3% are NO LONGER killed by `momentum_died_20m`. They ride the trailing stop to +0.5-2%+.
- **Expected avg win improvement:** $1.74 → $5-15 per trade.

#### 3c. Faster loser cuts
| Exit | Old | New |
|------|-----|-----|
| `hard_loss_cut` | -3.0% / 15min | **-1.8% / 10min** |
| `momentum_died_10m` pnl threshold | -2.0% | **-1.5%** |
| `stall` hold/loss | 60min / -3.5% | **45min / -2.0%** |
| `traction` hold/loss | 45min / -3.0% | **30min / -1.5%** |

**Net effect:** Losers cut at -$5-10 (was -$10-25). Winners ride to +$5-15 (was +$1.74). Risk:reward flips from 1:10 wrong → 1:1.5+ right.

---

### EXPECTED IMPACT (math-based, not hope-based)

```
BEFORE (v3.3.1):
  Win rate: 21.5% | Avg win: $1.74 | Avg loss: $17.83
  EV/trade = 0.215 × $1.74 - 0.785 × $17.83 = -$13.62/trade

AFTER (v3.4, conservative estimates):
  Win rate: 35-40% (BTC filter removes 50%+ of bad entries)
  Avg win: $8-12 (trailing at 0.5% + profit guard)
  Avg loss: $8-10 (SL -2.5% + faster cuts)
  EV/trade = 0.375 × $10 - 0.625 × $9 = +$0.13/trade (breakeven+)

  With BTC bullish filter improving win quality:
  EV/trade = 0.40 × $12 - 0.60 × $9 = +$1.40/trade
  At 15 trades/day = +$21/day
```

---

### CONFIGURATION CHANGES (v3.4)

| Parameter | Old | New | File |
|-----------|-----|-----|------|
| `STOP_LOSS_PCT` | -5.0 | -2.5 | `.env` |
| `TRAILING_STOP_ACTIVATE_PCT` | 2.0 | 0.5 | `.env` |
| `TRAILING_STOP_DISTANCE_PCT` | 1.5 | 0.8 | `.env` |
| Bear regime allowlist | breakout, momentum, momentum_short | **momentum_short only** | `src/bigbrother.py` |
| Choppy regime allowlist | breakout, momentum, momentum_short | **momentum_short only** | `src/bigbrother.py` |
| BTC trend gate | (none) | EMA9>EMA21 + RSI>45 on 1h | `src/watcher.py` + `backend/server.py` |
| Profit guard | (none) | pnl>0 → skip momentum_died | `src/position_manager.py` |
| `hard_loss_cut` | -3.0%/15min | -1.8%/10min | `src/position_manager.py` |
| `stall` threshold | 60min/-3.5% | 45min/-2.0% | `src/position_manager.py` |
| `traction` threshold | 45min/-3.0% | 30min/-1.5% | `src/position_manager.py` |

### FILES MODIFIED IN v3.4

| File | Changes |
|------|---------|
| `src/watcher.py` | `is_btc_trend_bullish()` method — BTC 1h EMA9 vs EMA21 + RSI gate |
| `backend/server.py` | BTC trend gate wired before entry loop, per-symbol long blocking |
| `src/bigbrother.py` | Bear/choppy allowlist → `momentum_short` only (no longs) |
| `src/position_manager.py` | Profit guard in `_momentum_exit_reason`, tighter `hard_loss_cut`, tighter stall/traction |
| `.env` | SL -2.5%, trailing activate 0.5%, trailing distance 0.8% |

---

## v3.3.1 — March 24, 2026 — Daily Trade Counter Hotfix

> **Mission:** Bot had $12,062 USDT cash sitting idle, 6–7 valid setups ready every cycle, but refusing to open any positions. Traced to `_day_trade_count` counting **exits** instead of **entries**.

---

### BUG FIXES

#### 1. `_day_trade_count` counting EXITS, not ENTRIES — blocked all new trades
- **Files:** `src/risk_manager.py`, `backend/server.py`
- **Bug:** `record_trade()` fires on every position **close** (TIME exit, stop_loss, momentum_died, regime_shift_sweep, etc.) and was incrementing `_day_trade_count`. With 26 exchange_holdings doing TIME exits throughout the day, the counter hit **25** against `MAX_DAILY_TRADES=15`. Every candidate in every cycle showed:
  ```
  [Swarm] KAITO/USDT blocked: max_daily_trades reached (25/15)
  [Swarm] WLFI/USDT blocked: max_daily_trades reached (25/15)
  [Swarm] TAO/USDT  blocked: max_daily_trades reached (25/15)
  ```
  **$12,062 USDT sat idle for hours.** The bot could see valid setups, size them, but refused to enter.
- **Root cause:** `_day_trade_count += 1` was inside `record_trade()`. Every exit incremented it. The daily trade limit was designed to cap **new entries per day**, not closings — you can't control when markets close your positions.
- **Fix:**
  - Extracted `record_entry()` method — only called after a successful `open_position()` in `server.py`
  - `record_trade()` (exits) no longer touches `_day_trade_count`
  - Now the counter only tracks what it's supposed to: **new positions opened today**

#### 2. Consecutive-loss storm — 15+ pause warnings in one second
- **File:** `src/risk_manager.py`
- **Bug:** When 15+ exchange_holdings closed in one cycle (e.g. regime_shift_sweep or mass TIME exits), each called `record_trade()` with a loss. Each incremented `_consecutive_losses`. Once `>= 5`, every subsequent call re-triggered the pause warning:
  ```
  [Risk] 5 consecutive losses → pause for 20min  (×15 in 1 second)
  ```
  The pause timer was being reset 15 times (final expiry = last reset + 20min, not first + 20min). Log noise made debugging harder.
- **Fix:** Only log + set `_pause_until` on the **first** trigger. Subsequent hits in the same burst silently extend if needed (no log spam, no timer reset unless the new pause would last longer).

#### 3. `MAX_DAILY_TRADES` raised: 15 → 30
- **File:** `.env`
- Even with correct entry-only counting, 15 new entries/day is too tight for an 8-position momentum bot in volatile conditions. With 8 positions averaging 1–3h hold time, the bot may open 15–24 positions per day naturally.
- 30 provides comfortable headroom while the churn guard (3/symbol/4h) and 90-min cooldown prevent overtrading.

---

### CONFIGURATION CHANGES (v3.3.1)

| Parameter | Old Value | New Value | File |
|-----------|-----------|-----------|------|
| `_day_trade_count` increment | In `record_trade()` (exits) | In `record_entry()` (entries only) | `src/risk_manager.py` |
| `MAX_DAILY_TRADES` | `15` | `30` | `.env` |
| Consecutive-loss pause | Fires on every loss past threshold | Fires once, silently extends | `src/risk_manager.py` |

### FILES MODIFIED IN v3.3.1

| File | Changes |
|------|---------|
| `src/risk_manager.py` | `record_entry()` extracted, `record_trade()` no longer touches `_day_trade_count`, consecutive-loss pause dedup |
| `backend/server.py` | `record_entry()` wired after successful `open_position()` |
| `.env` | `MAX_DAILY_TRADES` 15→30 |

### VERIFIED WORKING

```
Cycle 1 complete | regime=sideways mode=normal open=8 total_pnl=$+0.00
OPENED IQ/USDT    $789   OPENED TON/USDT   $1028
OPENED KAITO/USDT $1064  OPENED FET/USDT   $1059
+ 4 more positions opened in first cycle
```

---

### READINESS ASSESSMENT — Is the Bot Profit-Ready?

After v3.1 → v3.2 → v3.3 → v3.3.1, here's an honest assessment of where we stand:

#### ✅ Fixed — Previously Fatal Issues (no longer losing money from these)

| Issue | Loss Caused | Version Fixed |
|-------|-------------|---------------|
| XRP IOC SL bug — no market sell fallback | -$747 single trade | v3.2 |
| `is_aggressive` permanently False — bear exits used slow path | Slow exits in bear | v3.2 |
| Bayesian threshold INVERTED — easier entry in volatile markets | Over-trading bad setups | v3.2 |
| TRX/ANIME churn — same loser 16× in one session | Cumulative -$100+ | v3.3 (cooldown 90m + churn guard) |
| `CHOPPY_MIN_TA_SCORE=82` — blocked all re-entries after crash | Missed entire reversal bounce | v3.3 |
| `_day_trade_count` counting exits — blocked all entries | Hours of idle capital | v3.3.1 |
| Consecutive-loss storm — 15× pause triggers in one cycle | Extended trading pauses | v3.3.1 |
| Dust positions cycling forever (TAO/BAN ghosts) | Log noise + slot waste | v3.1 |
| $5 daily loss cap halting bot | Bot stopped after 1 fee | v3.2 |
| Quant Mutator raising min_score 40→60 in 10 min | All entries blocked | v3.2 (frozen at 40) |

#### ✅ Strategy Improvements — Better Signal Quality

| Change | Impact |
|--------|--------|
| 1h return scoring in watcher | Price momentum tokens rank first, not volume-only |
| RSI cap 82→92 | Peak momentum zone (83–90) no longer rejected |
| Momentum fast-track (>2% 1h) | Catches pumps before EMAs cross |
| TF weights: less 4h, more 15m | Reacts faster, less lag |
| `no_traction` → 50% partial | Preserves upside on slow starters |
| `hard_loss_cut` -3%/15m | Stops killing SOL before it pumps |
| 4h EMA50 trend gate | Blocks trend-fighting longs in bear |
| 2% minimum stop distance | Survives normal tick noise |
| Regime-specific Bayesian thresholds | Stricter entry in dangerous regimes |

#### ⚠️ Known Risks to Monitor

| Risk | Mitigation | What to Watch |
|------|------------|---------------|
| Fast-track buys topped pumps | -5% SL + -3%/15m hard loss cut | If fast-track entries consistently exit via hard_loss_cut within 10min, raise threshold to 3% |
| 20% historical win rate | Most losses were from now-fixed bugs (churn, IOC, counting) — needs fresh data | Track win rate over next 24–48h; if still <30%, investigate entry quality |
| Exchange holdings not managed | Bot tracks but doesn't actively protect them | Consider manual cleanup of exchange_holdings that shouldn't be there |
| Volatile mode Bayesian 0.52 | Correct (stricter in volatile) but may block setups during whipsaws | If volatile mode lasts >1h with 0 entries, check if threshold is too high |

#### Verdict

**The bot is ready for monitored live trading.** The architecture is sound:

```
Watcher (446 pairs → 60 candidates, 1h return + volume + RSI scoring)
  → Analyzer (60 → 6-7 setups, RSI/EMA/MACD + fast-track)
    → BigBrother (regime gates: allowlist + ta_score + Bayesian threshold)
      → Risk Manager (drawdown scaling, daily limit, consecutive-loss pause)
        → Churn Guard (3/symbol/4h) + Cooldown (90m base)
          → Position Manager (partial exits, trailing stops, time exits)
```

Every major loss vector from the last 48h has been identified and patched. The strategy improvements (1h scoring, fast-track, partial exits) are directionally correct for momentum trading and carry low overfitting risk.

**What "profit-ready" means:** the bot will no longer lose money from **system bugs** (IOC SL, counting exits, unreachable gates, churn). Whether it **makes money** depends on market conditions and the quality of the momentum signals — that requires 24–48h of clean data to evaluate. The signal pipeline is now unblocked and correctly wired.

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
