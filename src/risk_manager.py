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
from typing import Optional
from loguru import logger

from .metrics import current_drawdown, win_rate, avg_r_multiple


# ── Account-size tier thresholds ──────────────────────────────────────────────
# Tuned for aggressive deployment (80-90% capital utilisation target):
#   kelly_mult   — applied as tier_mult = kelly_mult / 0.75 so medium = 1.0×
#   max_single   — per-position ceiling as fraction of equity
#   max_risk     — risk-based floor fallback when trade history is thin
ACCOUNT_TIER_THRESHOLDS = [
    (2_000,  "small",  0.50, 0.15, 0.05),   # (max_equity, tier, kelly_mult, max_single, max_risk)
    (20_000, "medium", 0.75, 0.25, 0.08),   # 25% per position × 4-5 slots ≈ 80-100% deployed
    (float("inf"), "large", 0.90, 0.25, 0.10),
]

# ── Drawdown-gradient size multipliers ────────────────────────────────────────
DRAWDOWN_SCALE = [
    (0.00, 0.03, 1.00),  # (dd_min, dd_max, size_mult)
    (0.03, 0.05, 0.80),
    (0.05, 0.10, 0.60),
    (0.10, 0.15, 0.40),  # safety mode active range — further de-risk
    (0.15, 1.00, 0.00),  # > 15%: full halt (also enforced in can_open_position)
]

# ── Win-streak bonus table ─────────────────────────────────────────────────────
WIN_STREAK_BONUS = [
    (5, 1.25),   # 5+ consecutive wins → +25%
    (3, 1.15),   # 3+ consecutive wins → +15%
    (0, 1.00),   # baseline
]


class RiskManager:
    """Multi-layer portfolio protection and position sizing."""

    def __init__(
        self,
        max_positions: int = 5,
        max_portfolio_exposure_pct: float = 0.30,
        max_single_exposure_pct: float = 0.08,
        max_risk_per_trade_pct: float = 0.01,
        max_drawdown_pct: float = 0.10,
        daily_loss_limit_pct: float = 0.03,
        consecutive_loss_threshold: int = 3,
        consecutive_loss_pause_minutes: int = 10,
        kelly_fraction: float = 0.5,
        max_kelly_fraction: float = 0.25,
        min_trades_for_kelly: int = 30,
        initial_equity: float = 1000.0,
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

        self.peak_equity = initial_equity
        self._day_start_equity = initial_equity
        self._day_start_time = _today_start()
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._pause_until: Optional[float] = None
        self._trade_history: list[dict] = []

        # Account tier — re-computed whenever detect_account_tier() is called
        # Defaults match the medium-tier row of ACCOUNT_TIER_THRESHOLDS so that
        # compute_position_size produces sensible values even if called before
        # detect_account_tier() (e.g. scaling path that skips can_open_position).
        self._account_tier: str = "medium"
        self._tier_kelly_mult: float = 0.75
        self._tier_max_single: float = 0.25
        self._tier_max_risk: float = 0.08

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
                self.max_risk_per_trade_pct = max(self.max_risk_per_trade_pct, max_risk * 0.5)
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
    ) -> tuple[bool, str]:
        """
        Check all risk gates. Returns (allowed: bool, reason: str).

        v3.1: regime_max_positions and regime_max_exposure_pct override defaults
        when the current regime calls for reduced capital deployment.
        """
        # Effective limits: use regime constraint if stricter than config
        eff_max_positions = min(
            self.max_positions,
            regime_max_positions if regime_max_positions is not None else self.max_positions,
        )
        eff_max_exposure = min(
            self.max_portfolio_exposure_pct,
            regime_max_exposure_pct if regime_max_exposure_pct is not None else self.max_portfolio_exposure_pct,
        )

        if open_count >= eff_max_positions:
            return False, f"max_positions reached ({open_count}/{eff_max_positions})"

        exposure_pct = current_exposure_usd / current_equity if current_equity > 0 else 0.0
        if exposure_pct >= eff_max_exposure:
            return False, f"max_exposure reached ({exposure_pct:.1%} >= {eff_max_exposure:.1%})"

        # Full halt when drawdown > 15%
        drawdown = self._compute_drawdown(current_equity)
        if drawdown >= 0.15:
            return False, f"drawdown_halt ({drawdown:.1%} > 15%)"

        if self._pause_until and time.time() < self._pause_until:
            remaining = int(self._pause_until - time.time())
            return False, f"consecutive_loss_pause ({remaining}s remaining)"

        self._refresh_day_stats(current_equity)
        day_pnl_pct = (current_equity - self._day_start_equity) / self._day_start_equity if self._day_start_equity > 0 else 0.0
        if day_pnl_pct <= -self.daily_loss_limit_pct:
            return False, f"daily_loss_limit hit ({day_pnl_pct:.1%})"

        if drawdown >= self.max_drawdown_pct:
            return False, f"max_drawdown hit ({drawdown:.1%})"

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
        tier_mult = self._tier_kelly_mult / 0.75   # normalise so medium=1.0×
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
        conviction_norm = max(0.0, min(1.0, (posterior - threshold) / max(1.0 - threshold, 0.01)))
        conviction_mult = 0.75 + conviction_norm * 0.65   # 0.75 – 1.40

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
        reg_mult = max(0.30, min(1.20, regime_size_mult))   # guard rails

        # ── Final size ────────────────────────────────────────────────────────
        size = base_size * conviction_mult * liq_mult * ta_mult * reg_mult
        size = min(size, max_single)   # hard cap
        size = max(size, 50.0)         # minimum order floor — never open a sub-$50 position

        logger.info(
            f"[Risk] {symbol} size=${size:.2f} "
            f"(base=${base_size:.2f} kelly=${kelly_size:.2f} risk=${risk_based:.2f} | "
            f"tier={self._account_tier}({tier_mult:.2f}×) dd={drawdown:.1%}({dd_mult:.2f}×) "
            f"streak={self._consecutive_wins}w({streak_mult:.2f}×) | "
            f"conv={conviction_mult:.2f}× liq={liq_mult:.2f}× ta={ta_mult:.2f}× "
            f"regime={reg_mult:.2f}×)"
        )
        return size

    def _drawdown_size_mult(self, drawdown: float) -> float:
        """Return size multiplier based on current drawdown level."""
        for dd_min, dd_max, mult in DRAWDOWN_SCALE:
            if dd_min <= drawdown < dd_max:
                return mult
        return 0.0

    def record_trade(self, pnl_usd: float, pnl_pct: float, r_multiple: float):
        """Record trade outcome for Kelly and circuit breaker logic."""
        won = pnl_usd > 0
        self._trade_history.append({
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "r_multiple": r_multiple,
            "won": won,
            "timestamp": int(time.time()),
        })
        if len(self._trade_history) > 500:
            self._trade_history = self._trade_history[-500:]

        if won:
            self._consecutive_losses = 0
            self._consecutive_wins += 1
        else:
            self._consecutive_wins = 0
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.consecutive_loss_threshold:
                self._pause_until = time.time() + self.consecutive_loss_pause_minutes * 60
                logger.warning(
                    f"[Risk] {self.consecutive_loss_threshold} consecutive losses → "
                    f"pause for {self.consecutive_loss_pause_minutes}min"
                )

        self._update_metrics()

    def update_peak_equity(self, equity: float):
        if equity > self.peak_equity:
            self.peak_equity = equity

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
            self._day_start_time = today

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
    today = datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc)
    return today.timestamp()
