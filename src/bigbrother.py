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
from typing import Optional
from loguru import logger
import httpx

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
    "bull":     {"max_exposure_pct": 0.90, "size_mult": 1.00},
    "sideways": {"max_exposure_pct": 0.82, "size_mult": 0.92},
    # BEAR: allow relative-strength longs + short tokens. Bayesian 0.52 + EMA50 gate.
    "bear":     {"max_exposure_pct": 0.55, "size_mult": 0.65},
    # CHOPPY: allow breakout longs + short tokens. Highest Bayesian bar (0.55).
    "choppy":   {"max_exposure_pct": 0.42, "size_mult": 0.55},
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
    "bull":     {"breakout", "momentum", "pullback", "consolidation_breakout", "mean_reversion"},
    "sideways": {"breakout", "momentum", "pullback", "consolidation_breakout"},
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
    "bull":     5,
    "sideways": 5,
    # BEAR/CHOPPY: fewer, higher-conviction entries only
    "bear":     3,
    "choppy":   3,
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
            "regime_max_positions": REGIME_MAX_POSITIONS.get(self.regime, 5),
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
        """Return capital deployment limits for the current regime."""
        cap = REGIME_CAPITAL.get(regime, REGIME_CAPITAL["sideways"])
        return {
            "max_exposure_pct": cap["max_exposure_pct"],
            "size_mult": cap["size_mult"],
            "max_positions": REGIME_MAX_POSITIONS.get(regime, 5),
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
        }

    def get_recent_events(self, n: int = 20) -> list[dict]:
        return self._events[-n:]
