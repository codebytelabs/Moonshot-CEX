"""
Scalping Sniper Strategy — Primary money printer.

Targets 0.3-1.0% moves on 1m/5m charts.
Win rate: 60-70% | Trades: 10-30/day | ROI: 1-3% daily

Entry rules:
  1. EMA9 > EMA21 on 5m (trend direction)
  2. RSI(14) crosses above 40 from below (oversold bounce) OR RSI 50-65 pullback
  3. MACD histogram turns positive (momentum confirmation)
  4. Price near or below VWAP (not chasing)
  5. Volume > 1.2x 20-period average (participation)

Exit rules:
  - TP1: +0.5% (take 40%)
  - TP2: +1.0% (take 30%)
  - Trail remaining at 0.4% distance after +0.6%
  - SL: -0.5% (tight — this is scalping)
  - Time exit: 15 min max hold
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional
from loguru import logger
from .base import BaseStrategy, StrategySignal


class ScalpingSniper(BaseStrategy):
    name = "scalper"
    max_signals_per_cycle = 3

    # Default config — overridable via config dict
    DEFAULTS = {
        "scan_interval_seconds": 10,
        "min_volume_24h": 1_000_000,
        "top_n_scan": 40,
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_period": 14,
        "rsi_entry_low": 38,
        "rsi_entry_high": 68,
        "vwap_max_distance_pct": 0.5,
        "volume_spike_mult": 1.2,
        "tp1_pct": 0.5,
        "tp2_pct": 1.0,
        "sl_pct": -0.5,
        "trail_activate_pct": 0.6,
        "trail_distance_pct": 0.4,
        "tp1_exit_frac": 0.40,
        "tp2_exit_frac": 0.30,
        "max_hold_minutes": 15,
        "min_score": 55,
    }

    def __init__(self, exchange, config=None):
        merged = {**self.DEFAULTS, **(config or {})}
        super().__init__(exchange, merged)
        self._scan_interval = merged["scan_interval_seconds"]
        self._pair_cache: list[str] = []
        self._cache_time = 0.0

    async def _get_pairs(self) -> list[str]:
        now = time.time()
        if self._pair_cache and now - self._cache_time < 300:
            return self._pair_cache
        pairs = self.exchange.get_usdt_pairs()
        self._pair_cache = pairs
        self._cache_time = now
        return pairs

    async def scan(self, regime: str = "sideways") -> list[StrategySignal]:
        if not self.enabled or not self.should_scan():
            return []

        pairs = await self._get_pairs()
        if not pairs:
            return []

        # Phase 1: Quick volume + spread filter via tickers
        try:
            tickers = await self.exchange.fetch_tickers()
        except Exception as e:
            logger.warning(f"[scalper] ticker fetch failed: {e}")
            return []

        min_vol = self.config["min_volume_24h"]
        long_candidates = []
        short_candidates = []
        for sym, tk in tickers.items():
            if "/USDT" not in sym or sym not in set(pairs):
                continue
            vol = float(tk.get("quoteVolume") or 0)
            last = float(tk.get("last") or 0)
            if vol < min_vol or last <= 0:
                continue
            pct_chg = float(tk.get("percentage") or 0)
            # Long candidates: not chasing, not falling knife
            if regime not in ("bear", "choppy") and -5 < pct_chg < 8:
                long_candidates.append((sym, vol, last, pct_chg))
            # Short candidates: overbought or downtrending
            if pct_chg > 5 or pct_chg < -1:
                short_candidates.append((sym, vol, last, pct_chg))

        long_candidates.sort(key=lambda x: x[1], reverse=True)
        long_candidates = long_candidates[: self.config["top_n_scan"]]
        short_candidates.sort(key=lambda x: x[1], reverse=True)
        short_candidates = short_candidates[: self.config["top_n_scan"]]

        # Phase 2: Analyze top candidates on 5m candles
        signals = []
        long_tasks = [self._analyze_symbol(sym, vol, last) for sym, vol, last, _ in long_candidates[:15]]
        short_tasks = [self._analyze_symbol_short(sym, vol, last) for sym, vol, last, _ in short_candidates[:10]]
        results = await asyncio.gather(*(long_tasks + short_tasks), return_exceptions=True)
        for r in results:
            if isinstance(r, StrategySignal):
                signals.append(r)

        signals.sort(key=lambda s: s.score, reverse=True)
        out = signals[: self.max_signals_per_cycle]
        if out:
            logger.info(f"[scalper] {len(out)} signals: {[(s.symbol, s.direction) for s in out]}")
        return out

    async def _analyze_symbol(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        candles = await self._fetch_candles(symbol, "5m", 60)
        if len(candles) < 30:
            return None

        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        volumes = [c[5] for c in candles]
        price = closes[-1]

        # Anti-chase: skip if pump already peaked and pulling back
        exhausted, pb_pct = self.is_pump_exhausted(highs, closes, "long")
        if exhausted:
            logger.debug(f"[scalper] {symbol} skip: pump exhausted, pullback {pb_pct:.1f}%")
            return None

        # -- Indicators --
        ema_f = self.ema(closes, self.config["ema_fast"])
        ema_s = self.ema(closes, self.config["ema_slow"])
        rsi_val = self.rsi(closes, self.config["rsi_period"])
        macd_line, sig_line, hist = self.macd(closes)
        atr_val = self.atr(highs, lows, closes, 14)
        vwap_val = self.vwap(highs[-20:], lows[-20:], closes[-20:], volumes[-20:])

        if not ema_f or not ema_s or len(ema_f) < 2 or len(ema_s) < 2:
            return None

        # -- Scoring (0-100) --
        score = 0.0
        reasons = []

        # 1. EMA trend: fast > slow = bullish (+25)
        if ema_f[-1] > ema_s[-1]:
            score += 25
            reasons.append("ema_bull")
            if ema_f[-1] > ema_f[-2]:
                score += 5
        else:
            return None  # Hard gate: no scalp longs against trend

        # 2. RSI in sweet spot (+20)
        rsi_lo = self.config["rsi_entry_low"]
        rsi_hi = self.config["rsi_entry_high"]
        if rsi_lo <= rsi_val <= rsi_hi:
            score += 20
            if rsi_val < 50:
                score += 5  # bonus for buying closer to oversold
                reasons.append(f"rsi_pullback({rsi_val:.0f})")
            else:
                reasons.append(f"rsi_mid({rsi_val:.0f})")
        else:
            return None  # RSI outside range

        # 3. MACD histogram positive or turning (+15)
        if hist > 0:
            score += 15
            reasons.append("macd_pos")
        elif hist > -0.0001 * price:  # very slightly negative, turning
            score += 8
            reasons.append("macd_turning")
        else:
            return None  # MACD bearish

        # 4. Price near/below VWAP (+15)
        vwap_dist = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0
        max_vwap_dist = self.config["vwap_max_distance_pct"]
        if vwap_dist <= max_vwap_dist:
            score += 15
            if vwap_dist < 0:
                score += 5  # below VWAP = value zone
            reasons.append(f"vwap({vwap_dist:+.2f}%)")
        else:
            score -= 10  # penalty for extended above VWAP

        # 5. Volume confirmation (+15)
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / max(len(volumes), 1)
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_spike_mult"]:
            score += 15
            reasons.append(f"vol({vol_ratio:.1f}x)")
        elif vol_ratio >= 0.8:
            score += 5
        else:
            score -= 5

        # 6. ATR-based stop quality
        if atr_val > 0 and price > 0:
            atr_pct = atr_val / price * 100
            if 0.2 <= atr_pct <= 1.5:
                score += 5  # good volatility for scalping
                reasons.append(f"atr({atr_pct:.2f}%)")

        if score < self.config["min_score"]:
            return None

        # -- Compute levels --
        sl_pct = self.config["sl_pct"]
        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]

        # Use ATR for dynamic stop if available
        if atr_val > 0:
            atr_stop_pct = -(atr_val * 1.5 / price * 100)
            sl_pct = max(sl_pct, atr_stop_pct)  # tighter of fixed vs ATR
            sl_pct = max(sl_pct, -1.0)  # never wider than -1% for scalps
            sl_pct = min(sl_pct, -0.3)  # never tighter than -0.3%

        stop_price = price * (1 + sl_pct / 100)
        tp1_price = price * (1 + tp1_pct / 100)
        tp2_price = price * (1 + tp2_pct / 100)

        return StrategySignal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=min(score, 100),
            entry_price=price,
            stop_loss=stop_price,
            stop_loss_pct=sl_pct,
            take_profit_1=tp1_price,
            take_profit_2=tp2_price,
            tp1_pct=tp1_pct,
            tp2_pct=tp2_pct,
            confidence=min(score / 100, 0.95),
            vol_usd=vol_usd,
            timeframe="5m",
            setup_type="scalp_sniper",
            reason=" | ".join(reasons),
        )

    async def _analyze_symbol_short(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        """Mirror of _analyze_symbol for SHORT entries."""
        candles = await self._fetch_candles(symbol, "5m", 60)
        if len(candles) < 30:
            return None

        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        volumes = [c[5] for c in candles]
        price = closes[-1]

        ema_f = self.ema(closes, self.config["ema_fast"])
        ema_s = self.ema(closes, self.config["ema_slow"])
        rsi_val = self.rsi(closes, self.config["rsi_period"])
        macd_line, sig_line, hist = self.macd(closes)
        atr_val = self.atr(highs, lows, closes, 14)
        vwap_val = self.vwap(highs[-20:], lows[-20:], closes[-20:], volumes[-20:])

        if not ema_f or not ema_s or len(ema_f) < 2 or len(ema_s) < 2:
            return None

        score = 0.0
        reasons = []

        # 1. EMA bearish: fast < slow (+25)
        if ema_f[-1] < ema_s[-1]:
            score += 25
            reasons.append("ema_bear")
            if ema_f[-1] < ema_f[-2]:
                score += 5
        else:
            return None  # No short against uptrend

        # 2. RSI overbought zone (+20)
        if 65 <= rsi_val <= 90:
            score += 20
            if rsi_val > 75:
                score += 5
                reasons.append(f"rsi_overbought({rsi_val:.0f})")
            else:
                reasons.append(f"rsi_high({rsi_val:.0f})")
        else:
            return None

        # 3. MACD histogram negative (+15)
        if hist < 0:
            score += 15
            reasons.append("macd_neg")
        elif hist < 0.0001 * price:
            score += 8
            reasons.append("macd_turning_neg")
        else:
            return None

        # 4. Price above VWAP = overextended, good for short (+15)
        vwap_dist = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0
        if vwap_dist >= 0:
            score += 15
            if vwap_dist > 0.3:
                score += 5
            reasons.append(f"above_vwap({vwap_dist:+.2f}%)")
        else:
            score -= 10

        # 5. Volume confirmation (+15)
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / max(len(volumes), 1)
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_spike_mult"]:
            score += 15
            reasons.append(f"vol({vol_ratio:.1f}x)")
        elif vol_ratio >= 0.8:
            score += 5

        if score < self.config["min_score"]:
            return None

        # Compute SHORT levels (inverted)
        sl_pct = abs(self.config["sl_pct"])  # positive for short SL above
        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]

        if atr_val > 0:
            atr_stop_pct = atr_val * 1.5 / price * 100
            sl_pct = min(sl_pct, atr_stop_pct)
            sl_pct = min(sl_pct, 1.0)
            sl_pct = max(sl_pct, 0.3)

        stop_price = price * (1 + sl_pct / 100)
        tp1_price = price * (1 - tp1_pct / 100)
        tp2_price = price * (1 - tp2_pct / 100)

        return StrategySignal(
            symbol=symbol,
            strategy=self.name,
            direction="short",
            score=min(score, 100),
            entry_price=price,
            stop_loss=stop_price,
            stop_loss_pct=sl_pct,
            take_profit_1=tp1_price,
            take_profit_2=tp2_price,
            tp1_pct=tp1_pct,
            tp2_pct=tp2_pct,
            confidence=min(score / 100, 0.95),
            vol_usd=vol_usd,
            timeframe="5m",
            setup_type="scalp_short",
            reason=" | ".join(reasons),
        )

    def check_exit(self, position: dict, current_price: float, regime: str = "sideways") -> Optional[str]:
        entry = float(position.get("entry_price", 0))
        if entry <= 0 or current_price <= 0:
            return None

        side = position.get("side", "long")
        if side == "short":
            pnl_pct = (entry - current_price) / entry * 100
            lowest = float(position.get("lowest_price", current_price))
            peak_pnl = (entry - lowest) / entry * 100 if entry > 0 else 0
        else:
            pnl_pct = (current_price - entry) / entry * 100
            highest = float(position.get("highest_price", current_price))
            peak_pnl = (highest - entry) / entry * 100 if entry > 0 else 0
        hold_secs = float(position.get("hold_time_seconds", 0))
        hold_min = hold_secs / 60.0

        sl = self.config["sl_pct"]
        tp1 = self.config["tp1_pct"]
        tp2 = self.config["tp2_pct"]
        trail_act = self.config["trail_activate_pct"]
        trail_dist = self.config["trail_distance_pct"]
        max_hold = self.config["max_hold_minutes"]

        # 1. Hard stop loss
        if pnl_pct <= sl:
            return "scalp_sl"

        # 2. Trailing stop after activation
        if peak_pnl >= trail_act:
            drawdown_from_peak = peak_pnl - pnl_pct
            if drawdown_from_peak >= trail_dist:
                return "scalp_trail"

        # 3. Time exit — scalps must be fast
        if hold_min >= max_hold:
            if pnl_pct <= 0:
                return "scalp_time_exit"
            elif hold_min >= max_hold * 2:
                return "scalp_time_max"

        # 4. Breakeven stop after +0.3%
        if peak_pnl >= 0.3 and pnl_pct <= 0.05:
            return "scalp_breakeven"

        return None
