"""
BigBrotherAgent — Autonomous supervisor.
Detects market regime (bull / sideways / bear / choppy), manages operating mode,
enforces per-regime exposure limits, monitors portfolio health, detects anomalies,
and provides LLM-powered explanations.

v3.1 — Regime-adaptive strategy:
  • 4-regime detection: bull | sideways | bear | choppy
  • Per-regime: size multiplier, max exposure, setup allowlist, exit params
  • Choppy = deadliest regime for momentum bots → minimal trading mode
"""
import time
import collections
from typing import Optional
from loguru import logger
import httpx
import numpy as np

from .risk_manager import RiskManager
from .bayesian_engine import BayesianDecisionEngine
from .alerts import AlertManager
from .metrics import current_drawdown, errors_total


REGIMES = ("bull", "sideways", "bear", "choppy")
MODES = ("normal", "volatile", "safety", "paused")

# ── Per-regime exit parameter scaling ──────────────────────────────────────────
# Applied as multipliers on top of the base config values passed at init time.
#   sl    = stop loss %    (higher = wider)
#   trail = trailing stop  (lower trail_activate = activates sooner)
#   time  = time exit hours
REGIME_SCALE = {
    # With simplified exits (SL + trailing + time only, no momentum kills),
    # trailing stop is the PRIMARY profit-capture mechanism. Scaling must ensure
    # trailing activates — never push trail_activate above 1.5% (base × scale).
    "bull":     {"sl": 1.4,  "trail": 1.3,  "time": 1.5},   # wider stops, longer rides
    "sideways": {"sl": 1.0,  "trail": 1.0,  "time": 1.0},   # default: SL=-3.5%, trail=1%/1%, time=2h
    "bear":     {"sl": 0.7,  "trail": 0.8,  "time": 0.75},  # SL=-2.45%, trail=0.8%/0.8%, time=1.5h
    "choppy":   {"sl": 0.65, "trail": 0.7,  "time": 0.75},  # SL=-2.28%, trail=0.7%/0.7%, time=1.5h
}

# ── Per-regime capital deployment limits ───────────────────────────────────────
# max_exposure_pct: max fraction of equity deployed simultaneously
# size_mult:        multiplier on RiskManager base position size
#
# Capital deployment per regime.
# BEAR/CHOPPY: deploy both long (relative-strength breakouts that pass the 4h
# EMA50 gate) AND short tokens simultaneously. The quality gates already prevent
# trend-fighting — no need for a blanket capital lockdown.
# Bull/sideways → full throttle with good TA confirmation.
REGIME_CAPITAL = {
    # max_single_pct: per-position margin as % of equity (dynamic, replaces static .env cap)
    # Bull: aggressive — 18% per position × 8 slots = up to 144% margin (leveraged)
    "bull":     {"max_exposure_pct": 0.90, "size_mult": 1.00, "max_single_pct": 0.18},
    # Sideways: base — 13% per position × 6 slots = up to 78% margin
    "sideways": {"max_exposure_pct": 0.78, "size_mult": 0.85, "max_single_pct": 0.13},
    # Bear: cautious — 10% per position × 4 slots = up to 40% margin
    "bear":     {"max_exposure_pct": 0.55, "size_mult": 0.65, "max_single_pct": 0.10},
    # Choppy: minimal — 8% per position × 3 slots = up to 24% margin
    "choppy":   {"max_exposure_pct": 0.42, "size_mult": 0.55, "max_single_pct": 0.08},
}

# ── Per-regime setup allowlist ─────────────────────────────────────────────────
# Only setups in the allowlist are considered for entry in that regime.
#
# BEAR: allow breakout + momentum for relative-strength longs (tokens that are
# ABOVE their own 4h EMA50 = outperforming the market) AND short tokens.
# The 4h EMA50 trend gate in analyzer.py blocks trend-fighting longs at the
# individual-token level — no need for a regime-level blanket ban.
# CHOPPY: breakout longs only (cleanest signal) + short tokens.
# pullback/mean_reversion are dangerous in bear/choppy (dip-buying in a downtrend).
REGIME_SETUP_ALLOWLIST = {
    "bull":     {"breakout", "momentum", "momentum_short", "pullback", "consolidation_breakout", "mean_reversion"},
    "sideways": {"breakout", "momentum", "momentum_short", "pullback", "consolidation_breakout"},
    # BEAR: momentum longs + shorts. The BTC trend gate (EMA9 >= EMA21*0.997, RSI>40)
    # blocks longs when BTC is genuinely dropping. Regime-level blanket ban was
    # redundant — it sat in 100% cash while alts pumped +11% (TAO, C, HUMA).
    "bear":     {"momentum", "momentum_short"},
    # CHOPPY: allow momentum longs. The BTC trend gate already blocks longs when BTC is genuinely bearish.
    # Choppy just means volatility, and alts can still pump +9% in choppy markets.
    "choppy":   {"momentum", "momentum_short"},
}

# Minimum ta_score required for bear/choppy regime entries.
# 50 gates low-quality noise but allows real momentum reversals through.
# Old value 82 was unreachable — blocked SOL(52), TAO(58), BTC(47) during
# reversal bounces, causing the bot to sit fully in cash.
CHOPPY_MIN_TA_SCORE = 50.0

# ── Per-regime max concurrent positions ───────────────────────────────────────
REGIME_MAX_POSITIONS = {
    "bull":     12,
    "sideways": 8,
    # BEAR/CHOPPY: fewer, higher-conviction entries only
    "bear":     5,
    "choppy":   4,
}

# ── Volatile mode overlay ──────────────────────────────────────────────────────
# When mode=volatile, reduce SIZE aggressively but keep position slots open.
# Volatile markets are OPPORTUNITIES (big swings to catch), but each bet
# should be smaller until win rate recovers.
# sideways+volatile: 5 max positions, 0.85 × 0.80 = 0.68× size
VOLATILE_MODE_OVERLAY = {
    "max_positions_mult": 1.0,    # keep all slots open — size_mult handles risk
    "size_mult":          0.80,   # reduce position size by 20%
    "exposure_mult":      0.80,   # reduce max exposure by 20%
}

# ── Per-regime Bayesian threshold override ────────────────────────────────────
# BigBrother RAISES the bar in dangerous regimes (more selective, not less).
# CRITICAL: volatile/bear threshold must be HIGHER than normal (0.45),
# not lower. Lower threshold = easier to enter in a bear market = bleeding.
REGIME_BAYESIAN_THRESHOLD = {
    "bull":     None,    # leave as QuantMutator / mode-computed value
    "sideways": None,    # leave as default (0.45)
    # BEAR: only the highest-conviction short-token setups pass
    "bear":     0.52,
    # CHOPPY: most restrictive — exceptional setups only
    "choppy":   0.55,
}


class BigBrotherAgent:
    """Supervisor agent — regime detection, mode management, anomaly monitoring."""

    def __init__(
        self,
        risk_manager: RiskManager,
        bayesian_engine: BayesianDecisionEngine,
        alerts: Optional[AlertManager] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        openrouter_model: str = "google/gemini-2.5-flash-lite-preview-09-2025",
        llm_macro_enabled: bool = False,
        regime_detection_interval_cycles: int = 10,
        bull_threshold: float = 3.0,
        bear_threshold: float = -3.0,
        max_drawdown_pct: float = 0.10,
        daily_loss_limit_pct: float = 0.03,
        stop_loss_pct: float = -5.0,
        trailing_activate_pct: float = 3.0,
        trailing_distance_pct: float = 2.5,
        time_exit_hours: float = 2.0,
    ):
        self.risk = risk_manager
        self.bayesian = bayesian_engine
        self.alerts = alerts
        self.api_key = openrouter_api_key
        self.api_base = openrouter_base_url
        self.model = openrouter_model
        self._llm_macro_enabled = llm_macro_enabled
        self.regime_interval = regime_detection_interval_cycles
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self._base_stop_loss_pct = stop_loss_pct
        self._base_trailing_activate_pct = trailing_activate_pct
        self._base_trailing_distance_pct = trailing_distance_pct
        self._base_time_exit_hours = time_exit_hours

        self.regime: str = "sideways"
        self.mode: str = "normal"
        self._cycle_count = 0
        self._events: list[dict] = []
        self._performance_window: list[dict] = []
        self._start_time = time.time()
        # track how many cycles we've held a given regime to avoid flapping
        self._regime_cycles: int = 0
        # LLM macro sentiment: cached score in [-1, +1], updated every 30 cycles
        self._llm_macro_score: float = 0.0   # 0 = neutral (default until first LLM call)
        self._llm_macro_label: str = "unknown"
        self._llm_macro_updated: int = 0      # cycle number of last LLM update
        self._llm_macro_interval: int = 30    # query LLM every 30 cycles (≈7.5 min)
        self._last_equity: float = 0.0        # last known equity for status summary drawdown

        # ── Supervisor loop state ────────────────────────────────────────────
        self._sv_interval: int = 8          # run every 8 cycles (≈2 min at 15s/cycle)
        self._sv_last_run: int = 0          # last cycle the supervisor ran
        # Rolling agent stats (last 20 cycles for trend detection)
        self._sv_agent_history: list[dict] = []   # [{watcher, analyzer, errors, ts}]
        self._sv_exchange_errors: int = 0    # cumulative exchange errors since last SV run
        self._sv_exchange_latency: list[float] = []  # recent API latencies
        # Position PnL snapshots for stagnation detection
        self._sv_pos_snapshots: dict[str, list[float]] = {}  # symbol → [pnl_pct history]
        # Last supervisor report (exposed via get_status_summary)
        self._sv_last_report: dict = {}

        # ── Position Health Monitor state ─────────────────────────────────────
        # Tracks per-position RSI snapshots for momentum reversal detection
        self._hm_rsi_snapshots: dict[str, list[float]] = {}  # symbol → [rsi history]

        # ── Self-Improvement Loop state ───────────────────────────────────────
        self._learning_log: list[dict] = []           # in-memory learning log
        self._learning_log_max: int = 200             # keep last 200 entries
        self._pattern_interval: int = 120             # run pattern detector every 120 cycles (~30 min)
        self._pattern_last_run: int = 0               # last cycle pattern detector ran
        self._confirmed_issues: list[dict] = []       # issues surfaced to dashboard
        self._confirmed_issues_max: int = 10          # max concurrent issues

    async def supervise(
        self,
        current_equity: float,
        open_count: int,
        closed_trades: list[dict],
        btc_ticker: Optional[dict] = None,
    ) -> dict:
        """
        Run one supervision cycle.
        Returns {regime, mode, regime_params, regime_capital, events}.
        """
        self._cycle_count += 1
        events = []

        # Track last equity for status reporting
        self._last_equity = current_equity
        # Update peak equity
        self.risk.update_peak_equity(current_equity)

        # Regime detection (every N cycles)
        if self._cycle_count % self.regime_interval == 0:
            # Fetch LLM macro signal asynchronously (fire & forget — never blocks cycle)
            if (
                self._llm_macro_enabled
                and self.api_key
                and (self._cycle_count - self._llm_macro_updated) >= self._llm_macro_interval
            ):
                try:
                    llm_signal = await self._fetch_llm_macro_sentiment()
                    if llm_signal["score"] != 0.0 or llm_signal["label"] != "unknown":
                        self._llm_macro_score = llm_signal["score"]
                        self._llm_macro_label = llm_signal["label"]
                        self._llm_macro_updated = self._cycle_count
                        logger.info(
                            f"[BigBrother] 🧠 LLM macro signal: {llm_signal['label']} "
                            f"(score={llm_signal['score']:+.2f}) — {llm_signal.get('reason', '')[:80]}"
                        )
                except Exception as _e:
                    logger.debug(f"[BigBrother] LLM macro fetch error: {_e}")

            new_regime = self._detect_regime(btc_ticker, closed_trades)
            if new_regime != self.regime:
                events.append(self._record_event("regime_change", f"{self.regime} → {new_regime}"))
                logger.info(f"[BigBrother] Regime: {self.regime} → {new_regime}")
                self._regime_cycles = 0
                if self.alerts:
                    await self.alerts.send(
                        f"🌐 Regime shift: *{self.regime}* → *{new_regime}*\n"
                        f"Exposure cap: {REGIME_CAPITAL[new_regime]['max_exposure_pct']:.0%} | "
                        f"Size: {REGIME_CAPITAL[new_regime]['size_mult']:.0%}×",
                        priority="medium",
                    )
                self.regime = new_regime
            else:
                self._regime_cycles += 1

            # Apply regime-specific Bayesian threshold override
            regime_threshold = REGIME_BAYESIAN_THRESHOLD.get(self.regime)
            if regime_threshold is not None:
                self.bayesian._thresholds["normal"] = max(
                    self.bayesian._thresholds.get("normal", 0.65),
                    regime_threshold,
                )

        # Mode management
        new_mode = self._compute_mode(current_equity, closed_trades)
        if new_mode != self.mode:
            events.append(self._record_event("mode_change", f"{self.mode} → {new_mode}"))
            logger.warning(f"[BigBrother] Mode: {self.mode} → {new_mode}")
            if self.alerts:
                await self.alerts.send(
                    f"⚙️ Mode change: *{self.mode}* → *{new_mode}*",
                    priority="high" if new_mode in ("safety", "paused") else "medium",
                )
            self.mode = new_mode
            self.bayesian.set_mode(new_mode if new_mode != "paused" else "safety")

        # Health check
        health = self.risk.check_portfolio_health(current_equity)
        drawdown = health["drawdown"]
        current_drawdown.set(drawdown)

        if drawdown >= self.max_drawdown_pct * 0.8:
            events.append(self._record_event("drawdown_warning", f"drawdown={drawdown:.1%}"))
            if self.alerts:
                await self.alerts.send(
                    f"⚠️ Drawdown warning: {drawdown:.1%} (limit: {self.max_drawdown_pct:.0%})",
                    priority="high",
                )

        regime_params = self._build_regime_params(self.regime)
        regime_capital = self._build_regime_capital(self.regime)

        return {
            "regime": self.regime,
            "mode": self.mode,
            "regime_params": regime_params,
            "regime_capital": regime_capital,
            "regime_setup_allowlist": list(REGIME_SETUP_ALLOWLIST.get(self.regime, set())),
            "choppy_min_ta_score": CHOPPY_MIN_TA_SCORE if self.regime in ("choppy", "bear") else 0.0,
            "regime_max_positions": regime_capital["max_positions"],
            "drawdown": round(drawdown, 4),
            "win_rate": health["win_rate"],
            "consecutive_losses": health["consecutive_losses"],
            "events": events,
        }

    def _build_regime_params(self, regime: str) -> dict:
        """Build exit parameter dict scaled for the current regime."""
        scale = REGIME_SCALE.get(regime, REGIME_SCALE["sideways"])
        sl = round(self._base_stop_loss_pct * scale["sl"], 2)
        ta = round(self._base_trailing_activate_pct * scale["trail"], 2)
        td = round(self._base_trailing_distance_pct * scale["trail"], 2)
        te = round(self._base_time_exit_hours * scale["time"], 2)
        return {
            "stop_loss_pct": sl,
            "trailing_activate_pct": ta,
            "trailing_distance_pct": td,
            "time_exit_hours": te,
        }

    def _build_regime_capital(self, regime: str) -> dict:
        """Return capital deployment limits for the current regime.
        When mode=volatile, applies VOLATILE_MODE_OVERLAY to reduce exposure."""
        cap = REGIME_CAPITAL.get(regime, REGIME_CAPITAL["sideways"])
        max_pos = REGIME_MAX_POSITIONS.get(regime, 6)
        size_m = cap["size_mult"]
        exp_pct = cap["max_exposure_pct"]

        # Volatile mode overlay: reduce everything when market is whipsaw
        if self.mode == "volatile":
            ov = VOLATILE_MODE_OVERLAY
            max_pos = max(2, int(max_pos * ov["max_positions_mult"]))
            size_m = round(size_m * ov["size_mult"], 3)
            exp_pct = round(exp_pct * ov["exposure_mult"], 3)

        return {
            "max_exposure_pct": exp_pct,
            "size_mult": size_m,
            "max_single_pct": cap.get("max_single_pct", 0.15),
            "max_positions": max_pos,
        }

    def _detect_regime(self, btc_ticker: Optional[dict], closed_trades: list[dict]) -> str:
        """
        4-regime detector: bull | sideways | bear | choppy.

        Signals:
          1. BTC 24h % change  (primary market direction)
          2. Recent win rate over last 20 trades (breadth of the bot's edge)
          3. Profit factor  (gross profit / gross loss — quality of wins)
          4. ATR expansion proxy via win rate volatility + short avg hold time
          5. Consecutive loss penalty

        Choppy regime is detected separately AFTER the bull/sideways/bear
        classification: it overrides "sideways" when win rate is poor AND
        closed trades suggest many short holds (whipsaws).
        """
        # ── Signal 1: BTC price change ───────────────────────────────────────
        btc_change = 0.0
        if btc_ticker:
            btc_change = float(btc_ticker.get("percentage") or 0.0)

        # ── Signal 2: Recent win rate & profit factor ─────────────────────────
        recent = closed_trades[-20:] if len(closed_trades) >= 20 else closed_trades
        if recent:
            wins = [t for t in recent if t.get("pnl_usd", 0) > 0]
            losses = [t for t in recent if t.get("pnl_usd", 0) <= 0]
            recent_wr = len(wins) / len(recent)
            gross_profit = sum(t.get("pnl_usd", 0) for t in wins)
            gross_loss = abs(sum(t.get("pnl_usd", 0) for t in losses)) or 1.0
            profit_factor = gross_profit / gross_loss
        else:
            recent_wr = 0.5
            profit_factor = 1.0

        # ── Signal 3: Consecutive loss penalty ──────────────────────────────
        health = self.risk.check_portfolio_health(self.risk.peak_equity)
        consec_losses = health.get("consecutive_losses", 0)
        loss_penalty = min(consec_losses * 0.5, 3.0)

        # ── Composite score: weighted bull/bear pressure (-10 → +10) ─────────
        score = (
            (btc_change / 3.0) * 4.0           # BTC: ±4 weight
            + (recent_wr - 0.5) * 8.0          # Win rate: ±4 weight
            + (profit_factor - 1.0) * 2.0      # Profit factor: ±2 weight
            - loss_penalty                      # Consecutive loss drag
        )

        if score >= 2.5:
            primary = "bull"
        elif score <= -2.0:
            primary = "bear"
        else:
            primary = "sideways"

        # ── LLM macro signal integration ────────────────────────────────────
        # LLM reads current BTC/macro news and returns a -1 to +1 score.
        # Adds ±1.5 to the composite score, acting as a leading indicator that
        # can push regime classification before TA metrics catch up.
        # Weight is 1.5 (modest: LLM overrides require TA confirmation too).
        if self._llm_macro_score != 0.0:
            score_with_llm = score + self._llm_macro_score * 1.5
            logger.debug(
                f"[BigBrother] Regime score: TA={score:.2f} + LLM={self._llm_macro_score:+.2f}×1.5 "
                f"= {score_with_llm:.2f} ({self._llm_macro_label})"
            )
            if score_with_llm >= 2.5 and primary != "bull":
                logger.info(f"[BigBrother] LLM macro upgraded regime: {primary} → bull")
                primary = "bull"
            elif score_with_llm <= -2.0 and primary != "bear":
                logger.info(f"[BigBrother] LLM macro downgraded regime: {primary} → bear")
                primary = "bear"

        # ── Choppy override ───────────────────────────────────────────────────
        # Choppy = sideways market but with volatile/whipsaw behaviour.
        # Indicators:
        #   - Win rate below 42% despite not being "bear" (score > -2)
        #   - Many very short holds (avg hold < 45 min) among recent losses
        #   - BTC change is between -1.5% and +1.5% (tight range)
        if primary in ("sideways", "bear"):
            avg_hold_h = self._avg_hold_hours(recent)
            choppy_signals = 0
            if recent_wr < 0.42:
                choppy_signals += 1
            if avg_hold_h > 0 and avg_hold_h < 0.75:  # avg hold < 45 min = whipsaws
                choppy_signals += 1
            if -1.5 < btc_change < 1.5:
                choppy_signals += 1

            if choppy_signals >= 2:
                logger.debug(
                    f"[BigBrother] Choppy detected: wr={recent_wr:.0%} avg_hold={avg_hold_h:.1f}h "
                    f"btc={btc_change:+.1f}%"
                )
                return "choppy"

        return primary

    def _avg_hold_hours(self, trades: list[dict]) -> float:
        """Compute average hold time in hours from recent closed trades."""
        holds = [t.get("hold_time_hours", 0.0) for t in trades if t.get("hold_time_hours", 0) > 0]
        if not holds:
            return 0.0
        return sum(holds) / len(holds)

    async def _fetch_llm_macro_sentiment(self) -> dict:
        """
        Query the LLM for current BTC/crypto macro market sentiment.
        Returns {score: float [-1,+1], label: str, reason: str}.
        Cached externally — only called every _llm_macro_interval cycles.
        """
        prompt = (
            "You are a crypto macro analyst. Based on the CURRENT market environment "
            "(today's BTC price action, macro news, fear/greed index, recent headlines), "
            "assess the overall crypto market regime.\n\n"
            "Respond ONLY with a valid JSON object with these exact fields:\n"
            '  {"score": <float from -1.0 to +1.0>, "label": "<bullish|neutral|bearish>", '
            '"reason": "<one sentence max>"}\n\n'
            "Score guide: +1.0 = strongly bullish macro, 0.0 = neutral, -1.0 = strongly bearish.\n"
            "Examples: market crash = -0.9, ETF inflows = +0.7, sideways = 0.0\n"
            "Be concise. Respond with JSON only, no markdown."
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://moonshot-cex.ai",
                        "X-Title": "Moonshot-CEX BigBrother",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 120,
                        "temperature": 0.1,
                    },
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"].strip()
                    # Parse JSON from response
                    import json as _json
                    start = raw.find("{")
                    end = raw.rfind("}") + 1
                    if start != -1 and end > 0:
                        parsed = _json.loads(raw[start:end])
                        score = float(parsed.get("score", 0.0))
                        score = max(-1.0, min(1.0, score))  # clamp to [-1, +1]
                        return {
                            "score": score,
                            "label": str(parsed.get("label", "neutral")),
                            "reason": str(parsed.get("reason", "")),
                        }
                else:
                    logger.debug(f"[BigBrother] LLM macro HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"[BigBrother] LLM macro error: {e}")
            errors_total.labels(component="bigbrother", error_type="llm_macro").inc()
        return {"score": 0.0, "label": "unknown", "reason": ""}

    def _compute_mode(self, equity: float, closed_trades: list[dict]) -> str:
        health = self.risk.check_portfolio_health(equity)

        # Only trigger safety on REALIZED drawdown — not capital deployed in open positions
        realized_drawdown = health["drawdown"]
        if realized_drawdown >= self.max_drawdown_pct and health["total_trades"] >= 3:
            return "safety"

        # Choppy regime → automatic volatile mode (raise Bayesian threshold)
        if self.regime == "choppy":
            return "volatile"

        recent = closed_trades[-10:] if len(closed_trades) >= 10 else closed_trades
        if recent:
            wins = sum(1 for t in recent if t.get("pnl_usd", 0) > 0)
            recent_wr = wins / len(recent)
            if recent_wr < 0.35:
                return "volatile"

        if health["paused"]:
            return "paused"

        return "normal"

    async def explain_decision(self, trade: dict) -> str:
        """Use LLM to explain a trade decision in plain English."""
        if not self.api_key:
            return "LLM explanations not configured."

        prompt = (
            f"Explain this crypto trade decision briefly (2-3 sentences max):\n"
            f"Symbol: {trade.get('symbol')}\n"
            f"Setup: {trade.get('setup_type')}\n"
            f"TA Score: {trade.get('ta_score')}\n"
            f"Posterior Probability: {trade.get('decision', {}).get('posterior')}\n"
            f"Sentiment: {trade.get('context', {}).get('sentiment')}\n"
            f"Regime: {self.regime}\n"
            f"Reasoning: {trade.get('decision', {}).get('reasoning')}\n"
            f"Write as if explaining to a trader. Be concise."
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 150,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.debug(f"[BigBrother] Explain error: {e}")
            errors_total.labels(component="bigbrother", error_type="llm_explain").inc()
        return "No explanation available."

    def _record_event(self, event_type: str, detail: str) -> dict:
        event = {
            "type": event_type,
            "detail": detail,
            "timestamp": int(time.time()),
        }
        self._events.append(event)
        if len(self._events) > 200:
            self._events = self._events[-200:]
        return event

    def get_status_summary(self) -> dict:
        uptime_hours = (time.time() - self._start_time) / 3600.0
        health = self.risk.check_portfolio_health(self._last_equity if self._last_equity > 0 else self.risk.peak_equity)
        return {
            "regime": self.regime,
            "mode": self.mode,
            "uptime_hours": round(uptime_hours, 2),
            "cycle_count": self._cycle_count,
            "regime_cycles": self._regime_cycles,
            "drawdown": health["drawdown"],
            "win_rate": health["win_rate"],
            "avg_r_multiple": health["avg_r_multiple"],
            "total_trades": health["total_trades"],
            "consecutive_losses": health["consecutive_losses"],
            "bayesian_priors": self.bayesian.get_status()["priors"],
            "regime_params": self._build_regime_params(self.regime),
            "regime_capital": self._build_regime_capital(self.regime),
            "regime_setup_allowlist": list(REGIME_SETUP_ALLOWLIST.get(self.regime, set())),
            # LLM macro signal — visible in /api/swarm/status for observability
            "llm_macro_score": self._llm_macro_score,
            "llm_macro_label": self._llm_macro_label,
            # Supervisor loop — last report summary
            "supervisor_verdict": self._sv_last_report.get("verdict", "N/A"),
            "supervisor_actions": len(self._sv_last_report.get("actions", [])),
            "supervisor_last_cycle": self._sv_last_run,
        }

    def get_recent_events(self, n: int = 20) -> list[dict]:
        return self._events[-n:]

    # ══════════════════════════════════════════════════════════════════════════
    # SUPERVISOR LOOP — comprehensive health audit every ~2 minutes
    # ══════════════════════════════════════════════════════════════════════════

    def record_agent_stats(
        self,
        watcher_candidates: int = 0,
        analyzer_setups: int = 0,
        cycle_errors: int = 0,
        api_latency: float = 0.0,
    ) -> None:
        """Called every cycle from server.py to feed telemetry into the supervisor."""
        self._sv_agent_history.append({
            "watcher": watcher_candidates,
            "analyzer": analyzer_setups,
            "errors": cycle_errors,
            "ts": time.time(),
        })
        # Keep last 30 cycles (~7.5 min of history)
        if len(self._sv_agent_history) > 30:
            self._sv_agent_history = self._sv_agent_history[-30:]
        if cycle_errors > 0:
            self._sv_exchange_errors += cycle_errors
        if api_latency > 0:
            self._sv_exchange_latency.append(api_latency)
            if len(self._sv_exchange_latency) > 30:
                self._sv_exchange_latency = self._sv_exchange_latency[-30:]

    async def supervisor_loop(
        self,
        positions: list,
        closed_trades: list,
        current_equity: float,
        position_manager=None,
        exchange=None,
        db=None,
    ) -> dict:
        """Comprehensive health audit — runs every ~2 minutes.

        Checks:
          1. Agent health (watcher/analyzer output + error rates)
          2. Strategy performance (expectancy, win rate trend, bleeding)
          3. Position validity (stagnant, thesis expired, holding too long)
          4. Concentration risk (correlated positions)
          5. Exchange health (API errors, latency)
          6. Self-healing actions (tighten stops, alerts, mode shifts)
          7. Position health monitor (live RSI/momentum check, close stale losers)
          8. Self-improvement pattern detector (every ~30 min)

        Returns dict with findings and actions taken.
        """
        self._sv_last_run = self._cycle_count
        report = {
            "cycle": self._cycle_count,
            "ts": int(time.time()),
            "checks": {},
            "actions": [],
            "alerts": [],
        }

        # ── 1. Agent Health ──────────────────────────────────────────────────
        agent_health = self._check_agent_health()
        report["checks"]["agent_health"] = agent_health
        if agent_health["status"] == "degraded":
            report["actions"].append(f"WARN: {agent_health['detail']}")
            report["alerts"].append(agent_health["detail"])
            self._record_event("supervisor_agent_degraded", agent_health["detail"])

        # ── 2. Strategy Performance ──────────────────────────────────────────
        strat_health = self._check_strategy_performance(closed_trades)
        report["checks"]["strategy"] = strat_health
        if strat_health["status"] == "bleeding":
            report["actions"].append(f"WARN: {strat_health['detail']}")
            report["alerts"].append(strat_health["detail"])
            self._record_event("supervisor_strategy_bleeding", strat_health["detail"])

        # ── 3. Position Validity ─────────────────────────────────────────────
        pos_checks = self._check_position_validity(positions)
        report["checks"]["positions"] = pos_checks
        for pc in pos_checks.get("stagnant", []):
            report["actions"].append(f"TIGHTEN: {pc['symbol']} stagnant {pc['detail']}")
            self._record_event("supervisor_pos_stagnant", f"{pc['symbol']}: {pc['detail']}")
        for pc in pos_checks.get("underwater_long", []):
            report["actions"].append(f"WATCH: {pc['symbol']} underwater {pc['detail']}")

        # Apply self-healing: tighten trailing stops on stagnant positions
        if position_manager and pos_checks.get("stagnant"):
            for pc in pos_checks["stagnant"]:
                await self._heal_stagnant_position(pc["pos"], position_manager)

        # ── 4. Concentration Risk ────────────────────────────────────────────
        concentration = self._check_concentration_risk(positions)
        report["checks"]["concentration"] = concentration
        if concentration["status"] == "high":
            report["actions"].append(f"WARN: {concentration['detail']}")
            report["alerts"].append(concentration["detail"])
            self._record_event("supervisor_concentration", concentration["detail"])

        # ── 5. Exchange Health ───────────────────────────────────────────────
        exchange_health = self._check_exchange_health()
        report["checks"]["exchange"] = exchange_health
        if exchange_health["status"] == "degraded":
            report["actions"].append(f"WARN: {exchange_health['detail']}")
            report["alerts"].append(exchange_health["detail"])
            self._record_event("supervisor_exchange_degraded", exchange_health["detail"])

        # ── 6. Position Health Monitor — live RSI/momentum check ───────────
        # Fetches 5m candles, computes RSI, closes stale losers with fading momentum.
        hm_closes = []
        if exchange and position_manager:
            hm_closes = await self._health_monitor_positions(
                positions, exchange, position_manager, db
            )
            report["checks"]["health_monitor"] = {
                "closed": [c["symbol"] for c in hm_closes],
                "count": len(hm_closes),
            }
            for hmc in hm_closes:
                report["actions"].append(
                    f"CLOSED: {hmc['symbol']} — {hmc['reason']} (PnL={hmc['pnl_pct']:+.1f}%)"
                )

        # ── 7. Self-Improvement Pattern Detector (every ~30 min) ───────────
        if (self._cycle_count - self._pattern_last_run) >= self._pattern_interval:
            self._pattern_last_run = self._cycle_count
            new_issues = self._detect_patterns(closed_trades)
            report["checks"]["pattern_detector"] = {
                "issues_found": len(new_issues),
                "total_learning_log": len(self._learning_log),
            }
            if new_issues:
                for issue in new_issues:
                    report["actions"].append(f"ISSUE: {issue['summary']}")
                    report["alerts"].append(issue["summary"])
                if self.alerts:
                    issue_text = "\n".join([f"• {i['summary']}" for i in new_issues])
                    await self.alerts.send(
                        f"🧠 Self-Improvement: {len(new_issues)} pattern(s) detected\n{issue_text}",
                        priority="high",
                    )

        # Attach confirmed issues to report for dashboard
        report["confirmed_issues"] = self._confirmed_issues

        # ── 8. Overall Verdict ───────────────────────────────────────────────
        critical_count = len(report["alerts"])
        if critical_count >= 3:
            report["verdict"] = "CRITICAL"
        elif critical_count >= 1:
            report["verdict"] = "WARNING"
        else:
            report["verdict"] = "HEALTHY"

        # Log summary
        action_count = len(report["actions"])
        pos_count = len([p for p in positions if getattr(p, "status", "") == "open"])
        logger.info(
            f"[Supervisor] Cycle {self._cycle_count} | verdict={report['verdict']} "
            f"positions={pos_count} actions={action_count} "
            f"agents={'OK' if agent_health['status'] == 'healthy' else agent_health['status']} "
            f"strategy={strat_health['status']} "
            f"exchange={exchange_health['status']}"
        )
        if report["actions"]:
            for act in report["actions"]:
                logger.info(f"[Supervisor] → {act}")

        # Send alert if critical
        if self.alerts and critical_count > 0:
            alert_text = "\n".join([f"• {a}" for a in report["alerts"]])
            await self.alerts.send(
                f"🔍 Supervisor ({report['verdict']}): {critical_count} issue(s)\n{alert_text}",
                priority="high" if critical_count >= 3 else "medium",
            )

        self._sv_last_report = report
        # Reset per-interval counters
        self._sv_exchange_errors = 0
        return report

    # ── Supervisor check implementations ─────────────────────────────────────

    def _check_agent_health(self) -> dict:
        """Are watcher and analyzer producing output? Any error spikes?"""
        history = self._sv_agent_history
        if len(history) < 3:
            return {"status": "healthy", "detail": "insufficient data"}

        recent = history[-8:]  # last 8 cycles (≈2 min)
        watcher_zeros = sum(1 for h in recent if h["watcher"] == 0)
        analyzer_zeros = sum(1 for h in recent if h["analyzer"] == 0)
        error_total = sum(h["errors"] for h in recent)
        avg_watcher = sum(h["watcher"] for h in recent) / len(recent)
        avg_analyzer = sum(h["analyzer"] for h in recent) / len(recent)

        issues = []
        # Watcher producing zero candidates for most cycles = something broken
        if watcher_zeros >= 6:
            issues.append(f"Watcher returned 0 candidates in {watcher_zeros}/{len(recent)} cycles")
        # Analyzer producing zero setups consistently (could be legitimate in choppy)
        # Only flag if watcher IS producing candidates but analyzer kills them all
        if analyzer_zeros >= 7 and avg_watcher > 10:
            issues.append(f"Analyzer produced 0 setups in {analyzer_zeros}/{len(recent)} cycles despite {avg_watcher:.0f} avg candidates")
        # Error spike
        if error_total >= 5:
            issues.append(f"{error_total} errors in last {len(recent)} cycles")

        if issues:
            return {"status": "degraded", "detail": "; ".join(issues),
                    "avg_watcher": round(avg_watcher, 1), "avg_analyzer": round(avg_analyzer, 1)}
        return {"status": "healthy", "detail": "OK",
                "avg_watcher": round(avg_watcher, 1), "avg_analyzer": round(avg_analyzer, 1)}

    def _check_strategy_performance(self, closed_trades: list) -> dict:
        """Is the bot making money? Detect bleeding before drawdown triggers."""
        if len(closed_trades) < 5:
            return {"status": "healthy", "detail": "insufficient trades", "expectancy": 0}

        # Last 10 trades: rolling expectancy and win rate
        recent = closed_trades[-10:]
        wins = [t for t in recent if t.get("pnl_usd", 0) > 0]
        losses = [t for t in recent if t.get("pnl_usd", 0) <= 0]
        wr = len(wins) / len(recent) if recent else 0
        total_pnl = sum(t.get("pnl_usd", 0) for t in recent)
        expectancy = total_pnl / len(recent)
        avg_win = sum(t.get("pnl_usd", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("pnl_usd", 0) for t in losses) / len(losses) if losses else 0

        # Last 5 trades: short-term trend
        last5 = closed_trades[-5:]
        last5_pnl = sum(t.get("pnl_usd", 0) for t in last5)
        last5_wr = sum(1 for t in last5 if t.get("pnl_usd", 0) > 0) / len(last5) if last5 else 0

        result = {
            "win_rate_10": round(wr, 2),
            "expectancy": round(expectancy, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "last5_pnl": round(last5_pnl, 2),
            "last5_wr": round(last5_wr, 2),
        }

        # Bleeding: negative expectancy AND last 5 trades also negative
        if expectancy < -2.0 and last5_pnl < 0 and wr < 0.35:
            result["status"] = "bleeding"
            result["detail"] = (
                f"Negative expectancy ${expectancy:.2f}/trade, "
                f"WR={wr:.0%}, last 5 trades ${last5_pnl:+.2f}"
            )
        elif expectancy < 0 and wr < 0.40:
            result["status"] = "weak"
            result["detail"] = f"Expectancy ${expectancy:.2f}/trade, WR={wr:.0%}"
        else:
            result["status"] = "healthy"
            result["detail"] = f"Expectancy ${expectancy:.2f}/trade, WR={wr:.0%}"
        return result

    def _check_position_validity(self, positions: list) -> dict:
        """Are open positions still justified? Detect stagnation and zombies."""
        result = {"stagnant": [], "underwater_long": [], "healthy": 0, "total": 0}
        now = time.time()

        for pos in positions:
            if getattr(pos, "status", "") != "open":
                continue
            if getattr(pos, "setup_type", "") in ("synced_holding", "exchange_holding"):
                continue
            result["total"] += 1

            hold_h = pos.hold_time_hours()
            entry = pos.entry_price
            highest = getattr(pos, "highest_price", entry)
            current_pnl = pos.current_pnl_pct(highest)  # PnL at best point
            # Use last known price approximation from highest/lowest tracking
            # (actual price fetching happens in server.py, not here)
            peak_pnl = pos.current_pnl_pct(highest) if pos.side == "long" else pos.current_pnl_pct(getattr(pos, "lowest_price", entry))

            # Track PnL snapshots for stagnation detection
            sym = pos.symbol
            if sym not in self._sv_pos_snapshots:
                self._sv_pos_snapshots[sym] = []
            self._sv_pos_snapshots[sym].append(peak_pnl)
            # Keep last 10 snapshots (≈20 min of supervisor checks)
            if len(self._sv_pos_snapshots[sym]) > 10:
                self._sv_pos_snapshots[sym] = self._sv_pos_snapshots[sym][-10:]

            # ── Stagnant: held >45min, never exceeded +1.5%, peak PnL not growing ──
            snaps = self._sv_pos_snapshots.get(sym, [])
            if hold_h >= 0.75 and peak_pnl < 1.5 and len(snaps) >= 3:
                # Check if peak PnL hasn't improved over last 3 supervisor runs (≈6 min)
                pnl_range = max(snaps[-3:]) - min(snaps[-3:])
                if pnl_range < 0.3:  # PnL hasn't moved >0.3% in 6 minutes
                    result["stagnant"].append({
                        "symbol": sym,
                        "pos": pos,
                        "hold_h": round(hold_h, 2),
                        "peak_pnl": round(peak_pnl, 2),
                        "detail": f"held {hold_h:.1f}h, peak {peak_pnl:+.1f}%, PnL flat for {len(snaps[-3:])} checks",
                    })
                    continue

            # ── Underwater long: held >30min and consistently red ──
            if hold_h >= 0.5 and peak_pnl < 0:
                result["underwater_long"].append({
                    "symbol": sym,
                    "hold_h": round(hold_h, 2),
                    "peak_pnl": round(peak_pnl, 2),
                    "detail": f"held {hold_h:.1f}h, best PnL {peak_pnl:+.1f}% — never went green",
                })
                continue

            result["healthy"] += 1

        # Clean snapshots for closed positions
        open_syms = {getattr(p, "symbol", "") for p in positions if getattr(p, "status", "") == "open"}
        for sym in list(self._sv_pos_snapshots.keys()):
            if sym not in open_syms:
                del self._sv_pos_snapshots[sym]

        return result

    def _check_concentration_risk(self, positions: list) -> dict:
        """Are positions too correlated? Detect sector concentration."""
        open_pos = [p for p in positions if getattr(p, "status", "") == "open"
                    and getattr(p, "setup_type", "") not in ("synced_holding", "exchange_holding")]
        if len(open_pos) < 3:
            return {"status": "healthy", "detail": "too few positions to assess", "count": len(open_pos)}

        # Check: all positions same side (all long or all short)
        sides = [getattr(p, "side", "long") for p in open_pos]
        long_pct = sides.count("long") / len(sides)

        # Check: PnL correlation — if ALL positions are red or ALL are green,
        # they might be moving together (correlated with BTC)
        pnl_signs = []
        for p in open_pos:
            highest = getattr(p, "highest_price", p.entry_price)
            pnl = p.current_pnl_pct(highest) if p.side == "long" else p.current_pnl_pct(getattr(p, "lowest_price", p.entry_price))
            pnl_signs.append(1 if pnl > 0 else -1)

        all_same_sign = len(set(pnl_signs)) == 1 and len(pnl_signs) >= 3

        issues = []
        if long_pct == 1.0 and len(open_pos) >= 4:
            issues.append(f"All {len(open_pos)} positions are LONG — no hedge")
        if all_same_sign and pnl_signs[0] == -1:
            issues.append(f"All {len(open_pos)} positions are RED — highly correlated downturn")

        if issues:
            return {"status": "high", "detail": "; ".join(issues), "count": len(open_pos),
                    "long_pct": round(long_pct, 2)}
        return {"status": "healthy", "detail": "OK", "count": len(open_pos),
                "long_pct": round(long_pct, 2)}

    def _check_exchange_health(self) -> dict:
        """API error rate and latency check."""
        error_count = self._sv_exchange_errors
        latencies = self._sv_exchange_latency
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        max_lat = max(latencies) if latencies else 0

        issues = []
        if error_count >= 10:
            issues.append(f"{error_count} API errors since last check")
        elif error_count >= 5:
            issues.append(f"{error_count} API errors (elevated)")
        if avg_lat > 3.0:
            issues.append(f"Avg API latency {avg_lat:.1f}s (slow)")
        if max_lat > 10.0:
            issues.append(f"Max API latency {max_lat:.1f}s (timeout risk)")

        if issues:
            return {"status": "degraded", "detail": "; ".join(issues),
                    "error_count": error_count, "avg_latency": round(avg_lat, 2)}
        return {"status": "healthy", "detail": "OK",
                "error_count": error_count, "avg_latency": round(avg_lat, 2)}

    async def _heal_stagnant_position(self, pos, position_manager) -> None:
        """Self-healing: tighten trailing stop on stagnant positions.

        If a position has been flat for multiple supervisor checks, set a tight
        trailing stop to exit on the next small move rather than waiting for
        the full time_exit to clean it up.
        """
        try:
            current_price = await position_manager.execution.get_current_price(pos.symbol)
            if current_price <= 0:
                return

            pnl_pct = pos.current_pnl_pct(current_price)

            if pnl_pct > 0.3:
                # Green but stagnant — set tight trail at current minus 0.8%
                if pos.side == "long":
                    tight = current_price * 0.992
                    if pos.trailing_stop is None or tight > pos.trailing_stop:
                        pos.trailing_stop = tight
                        await position_manager._update_exchange_sl(pos, tight)
                        logger.info(
                            f"[Supervisor] {pos.symbol} stagnant+green → tight trail {tight:.6f} "
                            f"(pnl={pnl_pct:+.1f}%)"
                        )
                else:
                    tight = current_price * 1.008
                    if pos.trailing_stop is None or tight < pos.trailing_stop:
                        pos.trailing_stop = tight
                        await position_manager._update_exchange_sl(pos, tight)
                        logger.info(
                            f"[Supervisor] {pos.symbol} stagnant+green → tight trail {tight:.6f} "
                            f"(pnl={pnl_pct:+.1f}%)"
                        )
            # If red and stagnant — let stop_loss handle it, don't interfere
        except Exception as e:
            logger.debug(f"[Supervisor] Heal failed for {pos.symbol}: {e}")

    # ── Position Health Monitor ─────────────────────────────────────────────
    # Every ~2 min: fetch 5m candles for each open position, compute RSI,
    # detect momentum reversal, close stale losers with fading momentum.

    @staticmethod
    def _compute_rsi_from_closes(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    async def _health_monitor_positions(
        self, positions: list, exchange, position_manager, db=None
    ) -> list[dict]:
        """Live RSI/momentum check on every open position.

        Rules:
        - Position must be >2 min old
        - Position must be negative (PnL < 0)
        - Fetch 5m candles → compute RSI-14
        - LONG: RSI < 40 AND RSI declining (current < prev snapshot by 5+ pts) → close
        - SHORT: RSI > 60 AND RSI rising → close
        - Also close if momentum has fully reversed (RSI crossed 50 against position)
          AND position held > 5 min AND PnL < -1%

        Returns list of dicts describing each closed position.
        """
        closed_results = []
        now = time.time()

        for pos in positions:
            if getattr(pos, "status", "") != "open":
                continue
            if getattr(pos, "setup_type", "") in ("synced_holding", "exchange_holding"):
                continue

            symbol = pos.symbol
            hold_minutes = (now - pos.opened_at) / 60.0

            # Must be open > 2 minutes
            if hold_minutes < 2.0:
                continue

            try:
                current_price = await position_manager.execution.get_current_price(symbol)
                if current_price <= 0:
                    continue
                pnl_pct = pos.current_pnl_pct(current_price)
            except Exception:
                continue

            # Only check positions that are negative
            if pnl_pct >= 0:
                # Clean RSI snapshots for green positions
                self._hm_rsi_snapshots.pop(symbol, None)
                continue

            # Fetch 5m candles for RSI
            try:
                candles = await exchange.fetch_ohlcv(symbol, "5m", limit=30)
                if not candles or len(candles) < 16:
                    continue
                closes = np.array([c[4] for c in candles], dtype=float)
                rsi = self._compute_rsi_from_closes(closes, 14)
            except Exception as e:
                logger.debug(f"[HealthMonitor] Candle fetch failed for {symbol}: {e}")
                continue

            # Track RSI snapshots for trend detection
            if symbol not in self._hm_rsi_snapshots:
                self._hm_rsi_snapshots[symbol] = []
            self._hm_rsi_snapshots[symbol].append(rsi)
            if len(self._hm_rsi_snapshots[symbol]) > 5:
                self._hm_rsi_snapshots[symbol] = self._hm_rsi_snapshots[symbol][-5:]

            rsi_history = self._hm_rsi_snapshots[symbol]
            side = getattr(pos, "side", "long")
            close_reason = None

            if side == "long":
                # RSI < 40 and declining by 5+ pts from previous check → momentum gone
                if rsi < 40 and len(rsi_history) >= 2 and rsi_history[-2] - rsi >= 5:
                    close_reason = f"health_monitor_rsi_fade (RSI {rsi:.0f}, was {rsi_history[-2]:.0f})"
                # RSI crossed below 35 AND position > 5 min AND losing > 1%
                elif rsi < 35 and hold_minutes > 5.0 and pnl_pct < -1.0:
                    close_reason = f"health_monitor_momentum_lost (RSI {rsi:.0f}, PnL {pnl_pct:+.1f}%)"
            else:  # short
                # RSI > 60 and rising by 5+ pts → momentum reversed against short
                if rsi > 60 and len(rsi_history) >= 2 and rsi - rsi_history[-2] >= 5:
                    close_reason = f"health_monitor_rsi_bounce (RSI {rsi:.0f}, was {rsi_history[-2]:.0f})"
                # RSI crossed above 65 AND position > 5 min AND losing > 1%
                elif rsi > 65 and hold_minutes > 5.0 and pnl_pct < -1.0:
                    close_reason = f"health_monitor_momentum_lost (RSI {rsi:.0f}, PnL {pnl_pct:+.1f}%)"

            if close_reason:
                logger.info(
                    f"[HealthMonitor] CLOSING {symbol} ({side}): {close_reason} | "
                    f"hold={hold_minutes:.1f}min PnL={pnl_pct:+.1f}%"
                )
                try:
                    result = await position_manager._execute_exit(
                        pos, current_price, close_reason, pos.amount
                    )
                    if result:
                        closed_results.append({
                            "symbol": symbol,
                            "reason": close_reason,
                            "pnl_pct": round(pnl_pct, 2),
                            "pnl_usd": float(result.get("pnl_usd", 0)),
                            "hold_min": round(hold_minutes, 1),
                            "rsi": round(rsi, 1),
                            "side": side,
                            "result": result,
                        })
                        # Log lesson for self-improvement
                        self._log_lesson(pos, result, close_reason, rsi)
                except Exception as e:
                    logger.warning(f"[HealthMonitor] Exit failed for {symbol}: {e}")

        # Clean RSI snapshots for closed/missing positions
        open_syms = {getattr(p, "symbol", "") for p in positions if getattr(p, "status", "") == "open"}
        for sym in list(self._hm_rsi_snapshots.keys()):
            if sym not in open_syms:
                del self._hm_rsi_snapshots[sym]

        if closed_results:
            logger.info(f"[HealthMonitor] Closed {len(closed_results)} position(s) with fading momentum")

        return closed_results

    # ── Self-Improvement: Learning Log ────────────────────────────────────────

    def _log_lesson(self, pos, exit_result: dict, close_reason: str, rsi_at_close: float) -> None:
        """Record WHY a position was taken and WHY it was closed.

        Called on every health-monitor close. Can also be called externally
        for any losing trade close.
        """
        entry = {
            "ts": int(time.time()),
            "symbol": pos.symbol,
            "side": getattr(pos, "side", "long"),
            "setup_type": getattr(pos, "setup_type", "unknown"),
            "entry_price": pos.entry_price,
            "exit_price": float(exit_result.get("exit_price", 0)),
            "pnl_pct": float(exit_result.get("pnl_pct", 0)),
            "pnl_usd": float(exit_result.get("pnl_usd", 0)),
            "hold_minutes": round(pos.hold_time_hours() * 60, 1),
            "close_reason": close_reason,
            "rsi_at_close": round(rsi_at_close, 1),
            "regime_at_entry": self.regime,
            "mode_at_entry": self.mode,
            "decision": getattr(pos, "decision", {}),
            "lesson": self._generate_lesson(pos, close_reason, rsi_at_close),
        }
        self._learning_log.append(entry)
        if len(self._learning_log) > self._learning_log_max:
            self._learning_log = self._learning_log[-self._learning_log_max:]

        logger.info(
            f"[SelfImprove] LESSON: {entry['symbol']} {entry['side']} "
            f"setup={entry['setup_type']} regime={entry['regime_at_entry']} "
            f"PnL={entry['pnl_pct']:+.1f}% reason={close_reason} | {entry['lesson']}"
        )

    def log_losing_trade(self, trade_dict: dict) -> None:
        """Record a losing trade from normal exit flow (called from server.py)."""
        entry = {
            "ts": int(time.time()),
            "symbol": trade_dict.get("symbol", "?"),
            "side": trade_dict.get("side", "long"),
            "setup_type": trade_dict.get("setup_type", "unknown"),
            "entry_price": float(trade_dict.get("entry_price", 0)),
            "exit_price": float(trade_dict.get("exit_price", 0)),
            "pnl_pct": float(trade_dict.get("pnl_pct", 0)),
            "pnl_usd": float(trade_dict.get("pnl_usd", 0)),
            "hold_minutes": float(trade_dict.get("hold_minutes", 0)),
            "close_reason": trade_dict.get("close_reason", "unknown"),
            "rsi_at_close": 0.0,  # not available for normal exits
            "regime_at_entry": trade_dict.get("regime", self.regime),
            "mode_at_entry": trade_dict.get("mode", self.mode),
            "decision": trade_dict.get("decision", {}),
            "lesson": f"Lost {trade_dict.get('pnl_pct', 0):+.1f}% via {trade_dict.get('close_reason', '?')} "
                      f"after {trade_dict.get('hold_minutes', 0):.0f}min in {self.regime} regime",
        }
        self._learning_log.append(entry)
        if len(self._learning_log) > self._learning_log_max:
            self._learning_log = self._learning_log[-self._learning_log_max:]

    @staticmethod
    def _generate_lesson(pos, close_reason: str, rsi: float) -> str:
        side = getattr(pos, "side", "long")
        setup = getattr(pos, "setup_type", "unknown")
        hold_min = pos.hold_time_hours() * 60
        if "rsi_fade" in close_reason:
            return (f"Entered {side} {setup}, RSI faded to {rsi:.0f} after {hold_min:.0f}min — "
                    f"momentum was already exhausted at entry")
        if "momentum_lost" in close_reason:
            return (f"Entered {side} {setup}, momentum fully reversed (RSI={rsi:.0f}) "
                    f"after {hold_min:.0f}min — entry was against emerging trend")
        if "rsi_bounce" in close_reason:
            return (f"Short {setup} hit RSI bounce to {rsi:.0f} after {hold_min:.0f}min — "
                    f"selling pressure exhausted")
        return f"{side} {setup} closed after {hold_min:.0f}min: {close_reason}"

    # ── Self-Improvement: Pattern Detector ────────────────────────────────────

    def _detect_patterns(self, closed_trades: list) -> list[dict]:
        """Scan learning log + recent losing trades for repeated failure patterns.

        Runs every ~30 min. Looks for:
          1. Same setup_type losing 3+ times → "setup X is failing"
          2. Same regime producing 70%+ losers → "regime X is toxic"
          3. Positions dying within 5 min consistently → "entries too late"
          4. RSI range at entry correlating with losses → "bad RSI zone"

        Returns list of new confirmed issues.
        """
        new_issues = []
        cutoff = time.time() - 7200  # last 2 hours

        # Combine learning log + recent closed losing trades
        recent_lessons = [e for e in self._learning_log if e["ts"] > cutoff]

        # Also pull losing trades from closed_trades (last 20)
        recent_losers = []
        for t in closed_trades[-20:]:
            if float(t.get("pnl_usd", 0)) < 0:
                recent_losers.append({
                    "setup_type": t.get("setup_type", "unknown"),
                    "close_reason": t.get("close_reason", "unknown"),
                    "pnl_pct": float(t.get("pnl_pct", 0)),
                    "hold_minutes": float(t.get("hold_minutes", t.get("hold_time_hours", 0) * 60)),
                    "regime_at_entry": t.get("regime", "unknown"),
                    "side": t.get("side", "long"),
                })

        all_losses = recent_lessons + recent_losers
        if len(all_losses) < 3:
            return []

        # ── Pattern 1: Same setup_type failing repeatedly ─────────────────
        setup_counts = collections.Counter(e.get("setup_type", "?") for e in all_losses)
        for setup, count in setup_counts.items():
            if count >= 3 and setup != "unknown":
                issue_id = f"setup_failing:{setup}"
                if not self._issue_already_confirmed(issue_id):
                    issue = {
                        "id": issue_id,
                        "severity": "high" if count >= 5 else "medium",
                        "summary": f"Setup '{setup}' has failed {count}x in last 2h — review entry quality gates",
                        "count": count,
                        "ts": int(time.time()),
                        "category": "setup_type",
                    }
                    new_issues.append(issue)
                    self._add_confirmed_issue(issue)

        # ── Pattern 2: Same regime producing mostly losers ────────────────
        regime_stats = collections.defaultdict(lambda: {"wins": 0, "losses": 0})
        for t in closed_trades[-30:]:
            r = t.get("regime", "unknown")
            if float(t.get("pnl_usd", 0)) > 0:
                regime_stats[r]["wins"] += 1
            else:
                regime_stats[r]["losses"] += 1
        for regime, stats in regime_stats.items():
            total = stats["wins"] + stats["losses"]
            if total >= 5 and stats["losses"] / total >= 0.70:
                issue_id = f"regime_toxic:{regime}"
                if not self._issue_already_confirmed(issue_id):
                    wr = stats["wins"] / total * 100
                    issue = {
                        "id": issue_id,
                        "severity": "high",
                        "summary": (f"Regime '{regime}' has {wr:.0f}% win rate over last {total} trades "
                                    f"— consider pausing entries in this regime"),
                        "count": total,
                        "ts": int(time.time()),
                        "category": "regime",
                    }
                    new_issues.append(issue)
                    self._add_confirmed_issue(issue)

        # ── Pattern 3: Positions dying within 5 min consistently ──────────
        quick_deaths = [e for e in all_losses if e.get("hold_minutes", 999) < 5.0]
        if len(quick_deaths) >= 3:
            issue_id = "quick_death_pattern"
            if not self._issue_already_confirmed(issue_id):
                issue = {
                    "id": issue_id,
                    "severity": "high",
                    "summary": f"{len(quick_deaths)} positions died within 5 min — entries may be chasing exhausted moves",
                    "count": len(quick_deaths),
                    "ts": int(time.time()),
                    "category": "timing",
                }
                new_issues.append(issue)
                self._add_confirmed_issue(issue)

        # ── Pattern 4: Same close_reason repeated ─────────────────────────
        reason_counts = collections.Counter()
        for e in all_losses:
            # Normalize close reason to base category
            reason = e.get("close_reason", "unknown")
            if "rsi_fade" in reason:
                reason_counts["rsi_fade"] += 1
            elif "momentum_lost" in reason:
                reason_counts["momentum_lost"] += 1
            elif "stop_loss" in reason:
                reason_counts["stop_loss"] += 1
            elif "time_exit" in reason:
                reason_counts["time_exit"] += 1
            elif "trailing" in reason:
                reason_counts["trailing_stop"] += 1
            else:
                reason_counts[reason] += 1

        for reason, count in reason_counts.items():
            if count >= 4:
                issue_id = f"exit_pattern:{reason}"
                if not self._issue_already_confirmed(issue_id):
                    issue = {
                        "id": issue_id,
                        "severity": "medium",
                        "summary": f"Exit reason '{reason}' triggered {count}x in 2h — investigate root cause",
                        "count": count,
                        "ts": int(time.time()),
                        "category": "exit_reason",
                    }
                    new_issues.append(issue)
                    self._add_confirmed_issue(issue)

        if new_issues:
            logger.info(
                f"[SelfImprove] Pattern detector found {len(new_issues)} new issue(s) "
                f"from {len(all_losses)} recent losses"
            )

        return new_issues

    def _issue_already_confirmed(self, issue_id: str) -> bool:
        """Check if an issue is already in the confirmed list (avoid duplicates)."""
        return any(i["id"] == issue_id for i in self._confirmed_issues)

    def _add_confirmed_issue(self, issue: dict) -> None:
        """Add an issue to the confirmed list, evicting oldest if full."""
        # Remove stale issues (>4 hours old)
        cutoff = time.time() - 14400
        self._confirmed_issues = [i for i in self._confirmed_issues if i["ts"] > cutoff]
        self._confirmed_issues.append(issue)
        if len(self._confirmed_issues) > self._confirmed_issues_max:
            self._confirmed_issues = self._confirmed_issues[-self._confirmed_issues_max:]

    def dismiss_issue(self, issue_id: str) -> bool:
        """Dismiss a confirmed issue (called from dashboard API)."""
        before = len(self._confirmed_issues)
        self._confirmed_issues = [i for i in self._confirmed_issues if i["id"] != issue_id]
        return len(self._confirmed_issues) < before

    @property
    def confirmed_issues(self) -> list[dict]:
        """Return current confirmed issues for dashboard display."""
        # Evict stale issues on read
        cutoff = time.time() - 14400
        self._confirmed_issues = [i for i in self._confirmed_issues if i["ts"] > cutoff]
        return self._confirmed_issues

    @property
    def learning_log(self) -> list[dict]:
        """Return recent learning log entries."""
        return self._learning_log[-50:]

    @property
    def supervisor_due(self) -> bool:
        """True if supervisor_loop should run this cycle."""
        return (self._cycle_count - self._sv_last_run) >= self._sv_interval
