"""
Dynamic Leverage Engine — computes optimal leverage per trade.

Factors:
  - Signal confidence (score/100)
  - Market regime (bull/bear/sideways/volatile)
  - 24h volume (liquidity proxy)
  - Win streak / drawdown state
  - Funding rate (for perpetuals)

Output: integer leverage 1–max_leverage, clamped to safe bounds.
"""
from __future__ import annotations

from loguru import logger


class LeverageEngine:
    """Compute dynamic leverage for futures positions."""

    def __init__(
        self,
        default_leverage: int = 3,
        max_leverage: int = 10,
        min_leverage: int = 1,
        confidence_weight: float = 0.45,
        regime_weight: float = 0.15,
        btc_momentum_weight: float = 0.10,
        volume_weight: float = 0.10,
        streak_weight: float = 0.10,
        funding_weight: float = 0.10,
    ):
        self.default_leverage = default_leverage
        self.max_leverage = max_leverage
        self.min_leverage = min_leverage
        self.confidence_weight = confidence_weight
        self.regime_weight = regime_weight
        self.btc_momentum_weight = btc_momentum_weight
        self.volume_weight = volume_weight
        self.streak_weight = streak_weight
        self.funding_weight = funding_weight

    def compute_leverage(
        self,
        signal_score: float = 50.0,
        confidence: float = 0.5,
        regime: str = "sideways",
        vol_usd_24h: float = 0.0,
        win_streak: int = 0,
        consecutive_losses: int = 0,
        drawdown_pct: float = 0.0,
        funding_rate: float = 0.0,
        direction: str = "long",
        btc_momentum: float = 0.7,
    ) -> int:
        """Compute leverage as integer 1..max_leverage.

        Each factor produces a multiplier [0.0, 1.0] that is blended
        into a composite score, then mapped to the leverage range.
        """
        # ── Factor 1: Confidence (score + signal confidence) ──────────
        # Non-linear: amplify differences so high-quality signals get clearly
        # more leverage than mediocre ones (was linear → everything clustered at 0.55-0.65)
        norm_score = min(max(signal_score / 100.0, 0.0), 1.0)
        norm_conf = min(max(confidence, 0.0), 1.0)
        raw_conf = norm_score * 0.6 + norm_conf * 0.4
        # Power curve: low signals (0.3) → 0.09, mid (0.5) → 0.25, high (0.8) → 0.64
        confidence_factor = raw_conf ** 1.5 / (0.8 ** 1.5)  # normalized so 0.8 maps to ~1.0
        confidence_factor = min(max(confidence_factor, 0.0), 1.0)

        # ── Factor 2: Regime ──────────────────────────────────────────
        regime_map = {
            "bull": 1.0,
            "sideways": 0.55,
            "volatile": 0.35,
            "bear": 0.25,
            "choppy": 0.20,
        }
        regime_factor = regime_map.get(regime, 0.45)
        # For shorts in bear regime, flip the advantage
        if direction == "short" and regime in ("bear", "volatile"):
            regime_factor = 0.85

        # ── Factor 3: Volume/Liquidity ────────────────────────────────
        # Higher volume → safer to use leverage (less slippage risk)
        if vol_usd_24h >= 50_000_000:
            volume_factor = 1.0
        elif vol_usd_24h >= 10_000_000:
            volume_factor = 0.75
        elif vol_usd_24h >= 2_000_000:
            volume_factor = 0.50
        elif vol_usd_24h >= 500_000:
            volume_factor = 0.30
        else:
            volume_factor = 0.15

        # ── Factor 4: Win streak / drawdown ───────────────────────────
        # Hot hand → more leverage; drawdown → aggressively reduce
        if drawdown_pct > 5.0:
            streak_factor = 0.10
        elif drawdown_pct > 2.0:
            streak_factor = 0.30
        elif consecutive_losses >= 3:
            streak_factor = 0.20
        elif win_streak >= 5:
            streak_factor = 1.0
        elif win_streak >= 3:
            streak_factor = 0.80
        else:
            streak_factor = 0.50

        # ── Factor 5: Funding rate ────────────────────────────────────
        # Extreme positive funding → longs are expensive, reduce lev
        # Extreme negative funding → shorts are expensive, reduce lev
        abs_funding = abs(funding_rate)
        if abs_funding > 0.001:  # >0.1% per 8h is extreme
            if (funding_rate > 0 and direction == "long") or (funding_rate < 0 and direction == "short"):
                funding_factor = 0.20  # going against funding → reduce hard
            else:
                funding_factor = 0.90  # going with funding → favorable
        elif abs_funding > 0.0005:
            funding_factor = 0.50
        else:
            funding_factor = 0.70  # neutral funding

        # ── Factor 6: BTC Momentum ──────────────────────────────────
        # Alts correlate 0.6-0.95 with BTC. Strong BTC momentum → more leverage
        # for longs, less for shorts. Weak BTC → reduce long leverage.
        btc_mom_factor = min(max(btc_momentum, 0.0), 1.2)
        # For shorts: invert — weak BTC is good for shorts
        if direction == "short":
            btc_mom_factor = min(max(1.2 - btc_momentum, 0.0), 1.0)

        # ── Blend all factors ─────────────────────────────────────────
        composite = (
            confidence_factor * self.confidence_weight
            + regime_factor * self.regime_weight
            + btc_mom_factor * self.btc_momentum_weight
            + volume_factor * self.volume_weight
            + streak_factor * self.streak_weight
            + funding_factor * self.funding_weight
        )

        # Map [0, 1] → [min_leverage, max_leverage]
        raw_lev = self.min_leverage + composite * (self.max_leverage - self.min_leverage)
        leverage = int(max(self.min_leverage, min(self.max_leverage, round(raw_lev))))

        logger.info(
            f"[LevEngine] lev={leverage}x | conf={confidence_factor:.2f} reg={regime_factor:.2f} "
            f"btc={btc_mom_factor:.2f} vol={volume_factor:.2f} streak={streak_factor:.2f} "
            f"fund={funding_factor:.2f} composite={composite:.3f} "
            f"(score={signal_score:.0f} regime={regime} btc_mom={btc_momentum:.2f})"
        )
        return leverage

    def adjust_for_account_tier(self, leverage: int, equity: float) -> int:
        """Reduce max leverage for smaller accounts (more vulnerable to liquidation).

        v6.0 OVERHAUL: hard cap at 5x regardless of account size.
        Trade data showed high leverage (7-10x) amplified losses without
        improving win rate — smaller moves trigger stops on leveraged positions.
        """
        _HARD_CAP = 5
        if equity < 500:
            return min(leverage, 3, _HARD_CAP)
        elif equity < 2000:
            return min(leverage, 5, _HARD_CAP)
        return min(leverage, _HARD_CAP)
