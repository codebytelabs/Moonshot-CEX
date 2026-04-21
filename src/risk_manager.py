"""
RiskManager — Portfolio-level risk controls and position sizing.

v3.1 — Adaptive sizing:
  • Account-size tier detection → tiered Kelly fraction multiplier
    - Small  ($0   -$2K):   Kelly × 0.25  |  2-3  positions  |  1-2% risk
    - Medium ($2K  -$20K):  Kelly × 0.50  |  4-6  positions  |  3-5% risk
    - Large  ($20K+):       Kelly × 0.60  |  6-10 positions  |  5-8% risk

  • Drawdown-gradient sizing (pre-safety-mode de-risking):
    - 0-3% drawdown:  1.00× base
    - 3-5% drawdown:  0.80× base (pre-emptive caution)
    - 5-10% drawdown: 0.60× base (safety mode trigger range)
    - >15% drawdown:  full halt (checked in can_open_position)

  • Win-streak bonus (regime-gated — only in bull/sideways):
    - 3+ wins:  +15% size bonus
    - 5+ wins:  +25% size bonus (cap)

  • Regime size multiplier (injected from BigBrother):
    - Applied AFTER all other multipliers; caps always respected

  • Conviction × liquidity × TA quality multipliers unchanged from v3.0
"""

import time
import math
from typing import Optional
from loguru import logger

from .metrics import current_drawdown, win_rate, avg_r_multiple


# ── Account-size tier thresholds ──────────────────────────────────────────────
# Tuned for aggressive deployment (80-90% capital utilisation target):
#   kelly_mult   — applied as tier_mult = kelly_mult / 0.75 so medium = 1.0×
#   max_single   — per-position ceiling as fraction of equity
#   max_risk     — risk-based floor fallback when trade history is thin
ACCOUNT_TIER_THRESHOLDS = [
    (
        2_000,
        "small",
        0.50,
        0.12,
        0.05,
    ),  # (max_equity, tier, kelly_mult, max_single, max_risk)
    (
        20_000,
        "medium",
        0.75,
        0.18,
        0.08,
    ),  # 15-18% per position × 6-8 slots ≈ 90-144% deployed (leveraged)
    (float("inf"), "large", 0.90, 0.20, 0.10),
]

# ── Drawdown-gradient size multipliers ────────────────────────────────────────
DRAWDOWN_SCALE = [
    (0.00, 0.03, 1.00),  # (dd_min, dd_max, size_mult)
    (0.03, 0.05, 0.85),
    (0.05, 0.10, 0.65),
    (0.10, 0.15, 0.45),
    (0.15, 0.20, 0.30),  # reduced but STILL TRADING — 0.0× was a death spiral
    (0.20, 0.30, 0.20),  # deep drawdown: trade small to recover, never zero
    (0.30, 1.00, 0.15),  # extreme: minimum viable size, still in the game
]

# ── Win-streak bonus table ─────────────────────────────────────────────────────
WIN_STREAK_BONUS = [
    (5, 1.25),  # 5+ consecutive wins → +25%
    (3, 1.15),  # 3+ consecutive wins → +15%
    (0, 1.00),  # baseline
]


# ── v7.8.1: Per-setup sizing multiplier ───────────────────────────────────────
# Apply a size multiplier to specific setup_types. 1.0 = normal.
# Used to half-size restored or under-validated strategies until they prove out.
SETUP_SIZE_MULT: dict[str, float] = {
    # Validation period after the v7.8 restoration: 0/4 wins in live data.
    # Stay at half-size until at least SETUP_VALIDATION_GRAD_AFTER closes land.
    "ema_trend_follow": 0.5,
    # Live data (last 40 trades): 0W/5L, -$167.11, 0% WR. Half-size until it
    # recovers; CHIRON can promote a better multiplier once data supports it.
    "ema_ribbon_pullback": 0.5,
}

# ── v7.8.1: Per-setup circuit breaker ─────────────────────────────────────────
# If a setup_type's win rate over the last `window` closed trades is at or
# below `max_wr`, pause entries for that setup for `pause_minutes`. Keep other
# setups running normally. Prevents one bad strategy from dominating drawdown.
SETUP_CIRCUIT_BREAKERS: dict[str, dict] = {
    "ema_trend_follow": {"window": 5, "max_wr": 0.20, "pause_minutes": 120},
    # Live data: 0W/5L streak destroyed $167. Treat symmetrically with
    # ema_trend_follow so a losing streak pauses the setup for 2h.
    "ema_ribbon_pullback": {"window": 5, "max_wr": 0.20, "pause_minutes": 120},
}


class RiskManager:
    """Multi-layer portfolio protection and position sizing."""

    def __init__(
        self,
        max_positions: int = 5,
        max_portfolio_exposure_pct: float = 0.30,
        max_single_exposure_pct: float = 0.08,
        max_risk_per_trade_pct: float = 0.01,
        max_drawdown_pct: float = 0.25,
        daily_loss_limit_pct: float = 0.03,
        consecutive_loss_threshold: int = 3,
        consecutive_loss_pause_minutes: int = 10,
        kelly_fraction: float = 0.5,
        max_kelly_fraction: float = 0.25,
        min_trades_for_kelly: int = 30,
        initial_equity: float = 1000.0,
        max_daily_trades: int = 999,
        rolling_wr_window: int = 10,
        rolling_wr_floor: float = 0.30,
    ):
        self.max_positions = max_positions
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_single_exposure_pct = max_single_exposure_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.consecutive_loss_threshold = consecutive_loss_threshold
        self.consecutive_loss_pause_minutes = consecutive_loss_pause_minutes
        self.kelly_fraction = kelly_fraction
        self.max_kelly_fraction = max_kelly_fraction
        self.min_trades_for_kelly = min_trades_for_kelly

        self.max_daily_trades = max_daily_trades
        self.rolling_wr_window = rolling_wr_window
        self.rolling_wr_floor = rolling_wr_floor

        self.peak_equity = initial_equity
        self._day_start_equity = initial_equity
        self._day_start_time = _today_start()
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._pause_until: Optional[float] = None
        self._trade_history: list[dict] = []
        # v7.7: Rolling-WR cooldown uses SESSION trades only, not historical
        # seed. Without this, a restart after any bad-luck streak triggers a
        # 60-min cooldown on the first cycle, locking the fresh-fixed bot out.
        self._session_start_idx: int = 0
        self._day_trade_count: int = 0
        self._drawdown_halt_cycles: int = (
            0  # consecutive cycles blocked by drawdown_halt
        )
        self._entries_this_cycle: int = 0  # reset each cycle
        self._max_entries_per_cycle: int = 2  # cap scatter-shot entries

        # Account tier — re-computed whenever detect_account_tier() is called
        # Defaults match the medium-tier row of ACCOUNT_TIER_THRESHOLDS so that
        # compute_position_size produces sensible values even if called before
        # detect_account_tier() (e.g. scaling path that skips can_open_position).
        self._account_tier: str = "medium"
        self._tier_kelly_mult: float = 0.75
        self._tier_max_single: float = 0.25
        self._tier_max_risk: float = 0.08

        # v7.8.1: per-setup pause state. Key = setup_type, value = unix ts
        # after which the setup becomes allowed again. Not persisted across
        # restarts by design — startup recovery re-evaluates from history.
        self._setup_pause_until: dict[str, float] = {}
        self._runtime_setup_size_mult: dict[str, float] = {}
        self._runtime_setup_pause_until: dict[str, float] = {}

    def set_runtime_setup_overrides(
        self,
        size_mult: Optional[dict[str, float]] = None,
        pause_minutes: Optional[dict[str, int]] = None,
    ):
        self._runtime_setup_size_mult = {
            str(k): max(0.25, min(1.25, float(v)))
            for k, v in (size_mult or {}).items()
        }
        now = time.time()
        self._runtime_setup_pause_until = {
            str(k): now + max(1, int(v)) * 60 for k, v in (pause_minutes or {}).items()
        }

    def clear_runtime_setup_overrides(self):
        self._runtime_setup_size_mult = {}
        self._runtime_setup_pause_until = {}

    def get_effective_setup_size_multiplier(self, setup_type: Optional[str]) -> float:
        if not setup_type:
            return 1.0
        raw = self._runtime_setup_size_mult.get(
            setup_type, SETUP_SIZE_MULT.get(setup_type, 1.0)
        )
        return max(0.25, min(1.25, float(raw)))

    def get_runtime_setup_overrides(self) -> dict:
        return {
            "size_mult": dict(self._runtime_setup_size_mult),
            "pause_until": dict(self._runtime_setup_pause_until),
        }

    # ── Account-tier detection (call at startup and after equity updates) ──────
    def detect_account_tier(self, equity: float) -> str:
        """
        Detect account size tier and update dynamic risk parameters accordingly.
        Called at startup and any time equity crosses a tier boundary.
        """
        for max_eq, tier, k_mult, max_single, max_risk in ACCOUNT_TIER_THRESHOLDS:
            if equity <= max_eq:
                self._account_tier = tier
                self._tier_kelly_mult = k_mult
                self._tier_max_single = max_single
                self._tier_max_risk = max_risk
                # Respect original constructor caps — take the more conservative
                self.max_risk_per_trade_pct = max(
                    self.max_risk_per_trade_pct, max_risk * 0.5
                )
                logger.info(
                    f"[Risk] Account tier: {tier} (equity=${equity:,.0f}) → "
                    f"kelly_mult={k_mult:.2f}× max_single={max_single:.0%} max_risk={max_risk:.0%}"
                )
                return tier
        return self._account_tier

    def can_open_position(
        self,
        current_equity: float,
        open_count: int,
        current_exposure_usd: float,
        symbol: str = "",
        open_symbols: set = None,
        regime_max_positions: Optional[int] = None,
        regime_max_exposure_pct: Optional[float] = None,
        setup_type: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Check all risk gates. Returns (allowed: bool, reason: str).

        v3.1: regime_max_positions and regime_max_exposure_pct override defaults
        when the current regime calls for reduced capital deployment.
        """
        # Effective limits: BigBrother is regime-aware — trust its limits.
        # Use regime limit when provided (it handles both up/down: bull=10, bear=4).
        # Config max_positions is only the fallback when no regime data exists.
        eff_max_positions = (
            regime_max_positions
            if regime_max_positions is not None
            else self.max_positions
        )
        eff_max_exposure = min(
            self.max_portfolio_exposure_pct,
            regime_max_exposure_pct
            if regime_max_exposure_pct is not None
            else self.max_portfolio_exposure_pct,
        )

        if open_count >= eff_max_positions:
            return False, f"max_positions reached ({open_count}/{eff_max_positions})"

        exposure_pct = (
            current_exposure_usd / current_equity if current_equity > 0 else 0.0
        )
        if exposure_pct >= eff_max_exposure:
            return (
                False,
                f"max_exposure reached ({exposure_pct:.1%} >= {eff_max_exposure:.1%})",
            )

        # Drawdown recovery: if halted for N consecutive cycles, the peak is
        # likely stale/inflated (unrealized PnL pumped it up, then positions
        # closed at a loss). Reset peak to current equity so bot trades again.
        # Real drawdowns are handled by DRAWDOWN_SCALE (smaller sizing), not
        # permanent lockout.
        _DRAWDOWN_RECOVERY_CYCLES = 30  # ~15 min at 30s/cycle (was 100 = ~50 min)
        drawdown = self._compute_drawdown(current_equity)
        if drawdown >= 0.30:
            self._drawdown_halt_cycles += 1
            if self._drawdown_halt_cycles >= _DRAWDOWN_RECOVERY_CYCLES:
                old_peak = self.peak_equity
                self.peak_equity = current_equity
                self._drawdown_halt_cycles = 0
                logger.warning(
                    f"[Risk] Drawdown recovery: peak reset ${old_peak:,.2f} → ${current_equity:,.2f} "
                    f"after {_DRAWDOWN_RECOVERY_CYCLES} halted cycles (was {drawdown:.1%} drawdown)"
                )
                drawdown = 0.0  # allow this cycle through
            else:
                return (
                    False,
                    f"drawdown_halt ({drawdown:.1%} > 30%) [{self._drawdown_halt_cycles}/{_DRAWDOWN_RECOVERY_CYCLES} cycles]",
                )
        elif drawdown >= self.max_drawdown_pct:
            # Soft drawdown halt: same recovery mechanism but with shorter window.
            # Peak equity often inflated by unrealized gains that evaporated.
            self._drawdown_halt_cycles += 1
            if self._drawdown_halt_cycles >= _DRAWDOWN_RECOVERY_CYCLES:
                old_peak = self.peak_equity
                self.peak_equity = current_equity
                self._drawdown_halt_cycles = 0
                logger.warning(
                    f"[Risk] Soft drawdown recovery: peak reset ${old_peak:,.2f} → ${current_equity:,.2f} "
                    f"after {_DRAWDOWN_RECOVERY_CYCLES} halted cycles (was {drawdown:.1%} drawdown)"
                )
                drawdown = 0.0
            else:
                return (
                    False,
                    f"max_drawdown hit ({drawdown:.1%}) [{self._drawdown_halt_cycles}/{_DRAWDOWN_RECOVERY_CYCLES} cycles]",
                )
        else:
            self._drawdown_halt_cycles = 0  # reset counter when not halted

        if self._pause_until and time.time() < self._pause_until:
            remaining = int(self._pause_until - time.time())
            return False, f"consecutive_loss_pause ({remaining}s remaining)"

        self._refresh_day_stats(current_equity)
        day_pnl_pct = (
            (current_equity - self._day_start_equity) / self._day_start_equity
            if self._day_start_equity > 0
            else 0.0
        )
        if day_pnl_pct <= -self.daily_loss_limit_pct:
            return False, f"daily_loss_limit hit ({day_pnl_pct:.1%})"

        # Rolling win-rate gate: if last N trades have abysmal win rate,
        # trigger a 60-min cooldown then resume (avoids permanent deadlock).
        # v7.7: Only count SESSION trades — historical seed would trigger a
        # pause immediately after any restart following a bad streak.
        _session_trades = self._trade_history[self._session_start_idx :]
        if len(_session_trades) >= self.rolling_wr_window:
            recent = _session_trades[-self.rolling_wr_window :]
            wins = sum(1 for t in recent if t.get("won"))
            wr = wins / len(recent)
            if wr < self.rolling_wr_floor:
                if not self._pause_until or time.time() >= self._pause_until:
                    self._pause_until = time.time() + 60 * 60  # 60-min cooldown
                    logger.warning(
                        f"[Risk] Rolling WR {wins}/{len(recent)} = {wr:.0%} < {self.rolling_wr_floor:.0%} "
                        f"→ 60min cooldown"
                    )
                remaining = int(self._pause_until - time.time())
                return (
                    False,
                    f"rolling_winrate_cooldown ({wins}/{len(recent)} = {wr:.0%}, {remaining}s left)",
                )

        # v7.8.1: per-setup circuit breaker. Pauses a single setup_type without
        # affecting others. State is computed in record_trade() on each close.
        if setup_type:
            pause_until = max(
                self._setup_pause_until.get(setup_type, 0.0),
                self._runtime_setup_pause_until.get(setup_type, 0.0),
            )
            if pause_until and time.time() < pause_until:
                remaining = int(pause_until - time.time())
                return (
                    False,
                    f"setup_circuit_breaker:{setup_type} ({remaining}s left)",
                )

        return True, "ok"

    def compute_position_size(
        self,
        symbol: str,
        current_equity: float,
        stop_loss_pct: float,
        posterior: float = 0.65,
        threshold: float = 0.65,
        vol_usd: float = 0.0,
        ta_score: float = 50.0,
        regime: str = "sideways",
        regime_size_mult: float = 1.0,
        current_regime: str = "sideways",
        setup_type: Optional[str] = None,
    ) -> float:
        """
        Compute position size in USD — conviction-aware, liquidity-gated,
        account-size-tiered, drawdown-scaled, win-streak-boosted, regime-capped.

        Multiplier stack (applied on top of Kelly / risk-based base):
          1. Account-tier Kelly multiplier    (0.25× small → 0.60× large)
          2. Drawdown gradient               (1.00× healthy → 0.00× >15% halt)
          3. Win-streak bonus                (1.00× → 1.25× — only bull/sideways)
          4. Conviction (posterior vs thr)   (0.55× → 1.45×)
          5. Liquidity (24h vol_usd)         (0.45× → 1.00×)
          6. TA quality (ta_score 0-100)     (0.90× → 1.10×)
          7. Regime size multiplier          (0.45× choppy → 1.00× bull)

        Hard cap: never exceeds min(max_single_exposure_pct, tier_max_single_pct)
        """
        # Ensure tier is always current — calling detect_account_tier here means
        # size is correct even when the scaling path bypasses can_open_position.
        self.detect_account_tier(current_equity)

        # ── Tier-aware base size ───────────────────────────────────────────────
        kelly_size = self._kelly_size(current_equity)
        eff_max_single = min(self.max_single_exposure_pct, self._tier_max_single)
        eff_max_risk = max(self.max_risk_per_trade_pct, self._tier_max_risk)
        max_single = current_equity * eff_max_single
        risk_based = (
            current_equity * eff_max_risk / (abs(stop_loss_pct) / 100.0)
            if stop_loss_pct != 0
            else max_single
        )
        base_size = min(kelly_size, max_single, risk_based)

        # ── 1. Account-tier Kelly multiplier ─────────────────────────────────
        tier_mult = self._tier_kelly_mult / 0.75  # normalise so medium=1.0×
        # small=0.67×, medium=1.0×, large=1.20×
        base_size *= tier_mult

        # ── 2. Drawdown gradient ──────────────────────────────────────────────
        drawdown = self._compute_drawdown(current_equity)
        dd_mult = self._drawdown_size_mult(drawdown)
        base_size *= dd_mult

        # ── 3. Win-streak bonus (only in non-dangerous regimes) ───────────────
        streak_mult = 1.0
        if current_regime in ("bull", "sideways") and self._consecutive_wins > 0:
            for min_wins, bonus in WIN_STREAK_BONUS:
                if self._consecutive_wins >= min_wins:
                    streak_mult = bonus
                    break
        base_size *= streak_mult

        # ── 4. Conviction multiplier ──────────────────────────────────────────
        # Normalise over the full range (threshold → 1.0) so the multiplier
        # scales smoothly with real posterior values (0.45–0.90).
        # Floor raised to 0.75 so a barely-passing setup still gets 75% of base.
        conviction_norm = max(
            0.0, min(1.0, (posterior - threshold) / max(1.0 - threshold, 0.01))
        )
        conviction_mult = 0.75 + conviction_norm * 0.65  # 0.75 – 1.40

        # ── 5. Liquidity multiplier ───────────────────────────────────────────
        if vol_usd <= 0:
            liq_mult = 0.85
        elif vol_usd < 500_000:
            liq_mult = 0.45
        elif vol_usd < 2_000_000:
            liq_mult = 0.70
        elif vol_usd < 10_000_000:
            liq_mult = 0.88
        elif vol_usd < 50_000_000:
            liq_mult = 0.96
        else:
            liq_mult = 1.00

        # ── 6. TA quality multiplier ──────────────────────────────────────────
        ta_mult = 0.90 + (ta_score / 100.0) * 0.20

        # ── 7. Regime size multiplier (from BigBrother) ───────────────────────
        reg_mult = max(0.30, min(1.20, regime_size_mult))  # guard rails

        # ── 8. v7.8.1: Per-setup validation multiplier ────────────────────────
        # Let a restored or unproven strategy run at reduced size until it has
        # earned back full allocation. Hard-clipped to [0.25, 1.0] so a typo in
        # the table can't blow up sizing.
        setup_mult = 1.0
        if setup_type:
            setup_mult = self.get_effective_setup_size_multiplier(setup_type)

        # ── Final size ────────────────────────────────────────────────────────
        size = base_size * conviction_mult * liq_mult * ta_mult * reg_mult * setup_mult
        size = min(size, max_single)  # hard cap (% of equity)
        size = min(size, 5000.0)  # absolute hard cap — no single position > $5000
        # v8.0: $150 margin floor (was $50). Rationale from live data: positions
        # sized at $50-$100 generated trailing-stop wins averaging only $0.30-$0.80
        # — meaningful PnL requires enough skin in the game. Only apply when the
        # equity-percentage cap allows it (never exceed max_single).
        _floor = 150.0 if max_single >= 150.0 else 50.0
        size = max(size, _floor)
        size = min(size, max_single)  # final safety: respect equity cap after floor

        logger.info(
            f"[Risk] {symbol} size=${size:.2f} "
            f"(base=${base_size:.2f} kelly=${kelly_size:.2f} risk=${risk_based:.2f} | "
            f"tier={self._account_tier}({tier_mult:.2f}×) dd={drawdown:.1%}({dd_mult:.2f}×) "
            f"streak={self._consecutive_wins}w({streak_mult:.2f}×) | "
            f"conv={conviction_mult:.2f}× liq={liq_mult:.2f}× ta={ta_mult:.2f}× "
            f"regime={reg_mult:.2f}× setup={setup_mult:.2f}×)"
        )
        return size

    def compute_futures_position_size(
        self,
        symbol: str,
        current_equity: float,
        stop_loss_pct: float,
        leverage: int = 1,
        posterior: float = 0.65,
        threshold: float = 0.65,
        vol_usd: float = 0.0,
        ta_score: float = 50.0,
        regime: str = "sideways",
        regime_size_mult: float = 1.0,
        current_regime: str = "sideways",
        setup_type: Optional[str] = None,
    ) -> float:
        """Leverage-aware position sizing for futures.

        Key principle: MARGIN at risk per trade stays at 1-2% of equity.
        Notional = margin × leverage.

        With 5x leverage and $1000 equity:
          - margin_risk = 1% × $1000 = $10
          - notional = $10 × 5 = $50 position
          - If price moves -20% → loss = $50 × 20% = $10 = 1% of equity ✓

        The spot sizing logic runs first (without leverage) to get the
        risk-adjusted margin amount, then we multiply by leverage.
        """
        if leverage <= 1:
            return self.compute_position_size(
                symbol=symbol,
                current_equity=current_equity,
                stop_loss_pct=stop_loss_pct,
                posterior=posterior,
                threshold=threshold,
                vol_usd=vol_usd,
                ta_score=ta_score,
                regime=regime,
                regime_size_mult=regime_size_mult,
                current_regime=current_regime,
                setup_type=setup_type,
            )

        # For futures: compute margin (spot-equivalent) size first
        # Use tighter risk per trade for leveraged positions
        original_risk = self.max_risk_per_trade_pct
        self.max_risk_per_trade_pct = min(original_risk, 0.02)  # cap at 2% for futures

        margin_size = self.compute_position_size(
            symbol=symbol,
            current_equity=current_equity,
            stop_loss_pct=stop_loss_pct,
            posterior=posterior,
            threshold=threshold,
            vol_usd=vol_usd,
            ta_score=ta_score,
            regime=regime,
            regime_size_mult=regime_size_mult,
            current_regime=current_regime,
            setup_type=setup_type,
        )

        self.max_risk_per_trade_pct = original_risk

        # Notional = margin × leverage
        notional = margin_size * leverage

        # Hard caps for futures
        max_notional = (
            current_equity * 0.80 * leverage
        )  # deploy up to 80% equity as margin across positions
        notional = min(notional, max_notional)
        notional = min(notional, 50_000.0)  # absolute hard cap for futures notional
        # v8.0: $150 MARGIN floor (was $50 notional). Tiny positions produced
        # trailing wins averaging $0.30 — not worth the fee drag. Only lift
        # to $150 if the per-position equity-percentage cap headroom allows it.
        _min_margin = (
            150.0 if current_equity * self.max_single_exposure_pct >= 150.0 else 50.0
        )
        notional = max(notional, _min_margin * leverage)
        # Re-apply ALL ceilings after floor lift (order matters: the floor can
        # raise notional above any of the caps when equity is small).
        notional = min(notional, max_notional, 50_000.0)

        logger.info(
            f"[Risk] {symbol} FUTURES size: notional=${notional:.2f} "
            f"(margin=${margin_size:.2f} × {leverage}x) "
            f"max_margin_risk={self.max_risk_per_trade_pct:.1%}"
        )
        return notional

    def _drawdown_size_mult(self, drawdown: float) -> float:
        """Return size multiplier based on current drawdown level."""
        for dd_min, dd_max, mult in DRAWDOWN_SCALE:
            if dd_min <= drawdown < dd_max:
                return mult
        return 0.15  # never zero — 0.0× was a death spiral preventing recovery

    def reset_cycle_entries(self):
        """Reset per-cycle entry counter. Call at start of each cycle."""
        self._entries_this_cycle = 0

    def can_enter_this_cycle(self) -> tuple[bool, str]:
        """Check if more entries are allowed this cycle. Max 2 per cycle prevents scatter-shot."""
        if self._entries_this_cycle >= self._max_entries_per_cycle:
            return (
                False,
                f"max_entries_per_cycle ({self._entries_this_cycle}/{self._max_entries_per_cycle})",
            )
        return True, "ok"

    def record_entry(self):
        """Increment the daily entry counter. Call this once per new position open.
        Exits (TIME, momentum_died, stop_loss, etc.) must NOT count — only new entries do.
        Counting exits inflated the counter by 20-30 per day on volatile sessions, blocking
        all new trades while $12K sat idle."""
        self._day_trade_count += 1
        self._entries_this_cycle += 1

    def record_trade(
        self,
        pnl_usd: float,
        pnl_pct: float,
        r_multiple: float,
        setup_type: Optional[str] = None,
    ):
        """Record trade outcome for Kelly and circuit breaker logic.

        v7.8.1: setup_type is stored so the per-setup circuit breaker can
        evaluate a rolling window of trades for that specific strategy and
        pause it without affecting others.
        """
        won = pnl_usd > 0
        self._trade_history.append(
            {
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "r_multiple": r_multiple,
                "won": won,
                "timestamp": int(time.time()),
                "setup_type": setup_type,
            }
        )
        if len(self._trade_history) > 500:
            self._trade_history = self._trade_history[-500:]

        # v7.8.1: per-setup circuit breaker evaluation. Only evaluate the
        # setup that just closed. Pause for the configured minutes when the
        # rolling window WR is at or below the configured threshold.
        if setup_type and setup_type in SETUP_CIRCUIT_BREAKERS:
            cfg = SETUP_CIRCUIT_BREAKERS[setup_type]
            window = int(cfg.get("window", 5))
            max_wr = float(cfg.get("max_wr", 0.20))
            pause_minutes = int(cfg.get("pause_minutes", 120))
            setup_trades = [
                t for t in self._trade_history if t.get("setup_type") == setup_type
            ]
            if len(setup_trades) >= window:
                recent = setup_trades[-window:]
                wins = sum(1 for t in recent if t.get("won"))
                wr = wins / len(recent)
                if wr <= max_wr:
                    new_pause = time.time() + pause_minutes * 60
                    prev = self._setup_pause_until.get(setup_type)
                    if not prev or new_pause > prev:
                        self._setup_pause_until[setup_type] = new_pause
                        logger.warning(
                            f"[Risk] setup_circuit_breaker:{setup_type} "
                            f"{wins}/{len(recent)} = {wr:.0%} ≤ {max_wr:.0%} "
                            f"→ paused {pause_minutes}min"
                        )

        if won:
            self._consecutive_losses = 0
            self._consecutive_wins += 1
        else:
            self._consecutive_wins = 0
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.consecutive_loss_threshold:
                # v7.3 Graduated cooldown: ramp up pause with more consecutive losses.
                # 3 losses: 10min, 5 losses: 30min, 7+: 60min. Not binary.
                _graduated_pause_min = {
                    3: 10,
                    4: 20,
                    5: 30,
                    6: 45,
                    7: 60,
                }.get(min(self._consecutive_losses, 7), 60)
                new_pause = time.time() + _graduated_pause_min * 60
                if not self._pause_until or new_pause > self._pause_until:
                    first_trigger = not self._pause_until
                    self._pause_until = new_pause
                    if first_trigger:
                        logger.warning(
                            f"[Risk] {self._consecutive_losses} consecutive losses → "
                            f"graduated pause for {_graduated_pause_min}min"
                        )

        self._update_metrics()

    # ── Dynamic Risk Guardrails (v7.3) ────────────────────────────────────────
    # Risk params adapt per-trade to volatility, regime, and account health.
    # Just like leverage and sizing are dynamic, stops/trails/hold times should be too.

    def compute_dynamic_sl(self, atr_pct: float, regime: str = "sideways") -> float:
        """ATR-based dynamic stop loss. Volatile coins get wider SL, stable coins tighter.

        A fixed -4.5% SL on a coin that routinely swings 5%/hour guarantees stop-outs.
        Using 1.5-2x ATR(1h) gives each coin room proportional to its actual volatility.

        Returns negative percentage (e.g. -3.5).
        """
        # ATR multiplier by regime
        _regime_atr_mult = {"bull": 2.0, "sideways": 1.8, "bear": 1.5, "choppy": 1.5}
        mult = _regime_atr_mult.get(regime, 1.8)
        dynamic_sl = -(atr_pct * mult)
        # Clamp: never wider than -8% (blow-up risk), never tighter than -2% (noise)
        dynamic_sl = max(dynamic_sl, -8.0)
        dynamic_sl = min(dynamic_sl, -2.0)
        return round(dynamic_sl, 2)

    def compute_dynamic_exit_params(
        self, atr_pct: float, regime: str = "sideways", drawdown: float = 0.0
    ) -> dict:
        """Compute per-trade exit parameters adapted to volatility, regime, and drawdown.

        Returns dict with: stop_loss_pct, trailing_activate_pct, trailing_distance_pct, time_exit_hours
        """
        sl = self.compute_dynamic_sl(atr_pct, regime)

        # Trail activation: should be > noise but < typical move
        # ~0.7-1.0x ATR so normal moves activate trailing
        _trail_act_base = max(0.5, min(3.0, atr_pct * 0.8))
        _trail_dist_base = max(0.3, min(2.0, atr_pct * 0.5))

        # Regime-scale trailing
        _regime_trail_scale = {
            "bull": 1.3,
            "sideways": 1.0,
            "bear": 0.85,
            "choppy": 0.8,
        }
        _trail_scale = _regime_trail_scale.get(regime, 1.0)
        trail_activate = round(_trail_act_base * _trail_scale, 2)
        trail_dist = round(_trail_dist_base * _trail_scale, 2)

        # Time exit: bull = patient (4.5h), choppy = fast (2h)
        _regime_time = {"bull": 4.5, "sideways": 4.0, "bear": 3.0, "choppy": 2.5}
        time_hours = _regime_time.get(regime, 4.0)

        # Drawdown squeeze: when bleeding, tighten everything
        if drawdown > 0.10:
            trail_activate *= 0.8  # activate trail sooner
            time_hours *= 0.8  # shorter hold

        return {
            "stop_loss_pct": sl,
            "trailing_activate_pct": round(trail_activate, 2),
            "trailing_distance_pct": round(trail_dist, 2),
            "time_exit_hours": round(time_hours, 2),
        }

    def get_min_entry_score(self, drawdown: float = 0.0) -> float:
        """Drawdown-scaled entry quality bar. Higher bar when account is bleeding.

        Returns minimum ta_score required for entry.

        v7.7: Base lowered 50 → 42. The analyzer approves setups at ta >= 35
        (ANALYZER_MIN_SCORE) but the swarm gate was rejecting everything below 50,
        wasting 15 points of signal. Winning FAST-TRACK signals routinely have
        ta 40-49 (e.g. INIT ta=42 post=0.68 was rejected — exactly the kind of
        mid-quality trade where trailing stop earns its keep).
        Still scales up strictly in drawdown to preserve capital.
        """
        base_score = 42.0  # healthy baseline
        if drawdown > 0.15:
            return 68.0  # only the best setups when deep in drawdown
        elif drawdown > 0.10:
            return 60.0
        elif drawdown > 0.05:
            return 50.0
        return base_score

    def get_min_posterior(self, drawdown: float = 0.0) -> float:
        """Drawdown-scaled Bayesian posterior threshold."""
        base = 0.50
        if drawdown > 0.15:
            return 0.65
        elif drawdown > 0.10:
            return 0.58
        elif drawdown > 0.05:
            return 0.52
        return base

    def update_peak_equity(self, equity: float):
        if equity > self.peak_equity:
            self.peak_equity = equity

    def force_reset_peak(self, equity: float):
        """Force-reset peak equity to a specific value. Use when peak is known to be stale."""
        old = self.peak_equity
        self.peak_equity = equity
        self._drawdown_halt_cycles = 0
        logger.info(f"[Risk] Peak equity force-reset: ${old:,.2f} → ${equity:,.2f}")

    def check_portfolio_health(self, current_equity: float = None) -> dict:
        equity = current_equity or self.peak_equity
        drawdown = self._compute_drawdown(equity)
        recent = self._recent_trades(50)
        wr = _win_rate(recent)
        avg_r = _avg_r(recent)
        dd_mult = self._drawdown_size_mult(drawdown)

        return {
            "drawdown": round(drawdown, 4),
            "peak_equity": self.peak_equity,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "paused": self._pause_until is not None and time.time() < self._pause_until,
            "win_rate": round(wr, 4),
            "avg_r_multiple": round(avg_r, 3),
            "total_trades": len(self._trade_history),
            "recent_trades": len(recent),
            "account_tier": self._account_tier,
            "drawdown_size_mult": round(dd_mult, 2),
        }

    def _kelly_size(self, equity: float) -> float:
        recent = self._recent_trades(90)
        if len(recent) < self.min_trades_for_kelly:
            # Insufficient trade history — use the full tier max-single as the base.
            # The old fallback (equity × max_risk_per_trade_pct) produced $120 on a
            # $12K account; after stacked multipliers that became $4-$9 per trade.
            # Multipliers (conviction / liquidity / regime) then scale this down to
            # a real position size in the $800–$3K range for a $12K portfolio.
            return equity * self._tier_max_single

        wr = _win_rate(recent)
        avg_r = _avg_r(recent)
        if avg_r <= 0:
            return equity * self._tier_max_single

        kelly = wr - (1 - wr) / avg_r
        kelly = max(0.0, kelly)
        half_kelly = kelly * self.kelly_fraction
        capped = min(half_kelly, self.max_kelly_fraction)
        kelly_size = equity * capped

        # Floor: Kelly can return 0 during a losing streak (negative formula → clamped
        # to 0). Without a floor that collapses to the $10 minimum and, after partial
        # exits, produces $4-$9 runners.  Use 80% of the tier's per-position ceiling
        # as the absolute floor so multipliers (conviction/drawdown/regime) do the
        # de-risking instead of Kelly zeroing everything out.
        kelly_floor = equity * self._tier_max_single * 0.80
        return max(kelly_size, kelly_floor)

    def _compute_drawdown(self, equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity)

    def _recent_trades(self, n: int) -> list[dict]:
        return self._trade_history[-n:] if self._trade_history else []

    def _refresh_day_stats(self, equity: float):
        today = _today_start()
        if today > self._day_start_time:
            self._day_start_equity = equity
            self._day_trade_count = 0
            self._day_start_time = today
            # Reset session guards at day boundary so yesterday's loss streak
            # doesn't block a fresh trading day.
            self._consecutive_losses = 0
            self._consecutive_wins = 0
            self._pause_until = None
            self._setup_pause_until = {}
            self._session_start_idx = len(self._trade_history)
            logger.info("[Risk] New day — session guards reset (consecutive losses, pauses, setup CBs)")

    def _update_metrics(self):
        recent = self._recent_trades(50)
        wr = _win_rate(recent)
        avg_r = _avg_r(recent)
        win_rate.set(wr)
        avg_r_multiple.set(avg_r)


def _win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.5
    wins = sum(1 for t in trades if t.get("won", False))
    return wins / len(trades)


def _avg_r(trades: list[dict]) -> float:
    if not trades:
        return 1.5
    rs = [t.get("r_multiple", 0.0) for t in trades if t.get("won", False)]
    return sum(rs) / len(rs) if rs else 0.0


def _today_start() -> float:
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    today = datetime.datetime(
        now.year, now.month, now.day, tzinfo=datetime.timezone.utc
    )
    return today.timestamp()
