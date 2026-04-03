"""
PerformanceTracker — Rolling 7/30-day metrics, drawdown, win rate alerts.
Adapted from Moonshot-AutonomousAIMultiAgentCryptoBot for MongoDB backend.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


class PerformanceTracker:
    """
    Tracks rolling performance metrics from MongoDB trade history.

    Features:
    - Rolling 7-day & 30-day: win_rate, profit_factor, avg_r_multiple, daily_pnl
    - Equity curve construction
    - Alert thresholds: win_rate < 40%, drawdown > 15%
    - All-time aggregate metrics
    """

    WIN_RATE_ALERT_THRESHOLD = 40.0
    DRAWDOWN_ALERT_THRESHOLD = 15.0
    MIN_TRADES_FOR_ALERTS = 10

    def __init__(self, db=None):
        self._db = db

    # ── Public interface ───────────────────────────────────────────────────────

    async def get_current_metrics(self) -> Dict[str, Any]:
        """Full metrics snapshot — rolling 7d, 30d, all-time, equity curve."""
        now = datetime.now(timezone.utc)

        r7 = await self._rolling(now, 7)
        r30 = await self._rolling(now, 30)
        all_time = await self._all_time()
        curve = await self._equity_curve(now, 30)

        dd7 = self._drawdown_from_curve(curve[-7 * 10 :]) if curve else 0.0
        dd30 = self._drawdown_from_curve(curve) if curve else 0.0

        alerts = self._check_alerts(r7, dd7)

        return {
            "rolling_7day": {**r7, "drawdown": dd7},
            "rolling_30day": {**r30, "drawdown": dd30},
            "all_time": all_time,
            "equity_curve": curve[-60:],
            "alerts": alerts,
            "timestamp": now.isoformat(),
        }

    async def get_daily_summary(self) -> Dict[str, Any]:
        """Today's trades, open positions, rolling 7d snapshot, alerts."""
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        daily_trades = await self._fetch_trades(day_start, now)
        daily_pnl = sum(float(t.get("pnl", 0)) for t in daily_trades)

        r7 = await self._rolling(now, 7)
        dd7 = 0.0
        try:
            curve = await self._equity_curve(now, 7)
            dd7 = self._drawdown_from_curve(curve)
        except Exception:
            pass

        open_count = 0
        if self._db is not None:
            try:
                open_count = await self._db.positions.count_documents({"status": "open"})
            except Exception:
                pass

        return {
            "date": now.date().isoformat(),
            "trades_today": len(daily_trades),
            "open_positions": open_count,
            "daily_pnl": round(daily_pnl, 2),
            "rolling_7day": r7,
            "drawdown_7day": dd7,
            "alerts": self._check_alerts(r7, dd7),
            "timestamp": now.isoformat(),
        }

    # ── Core calculations ──────────────────────────────────────────────────────

    async def _rolling(self, end: datetime, days: int) -> Dict[str, Any]:
        start = end - timedelta(days=days)
        trades = await self._fetch_trades(start, end)

        if not trades:
            return {
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_r_multiple": 0.0,
                "daily_pnl": 0.0,
                "total_pnl": 0.0,
                "total_trades": 0,
                "window_days": days,
            }

        pnls = [float(t.get("pnl", 0)) for t in trades if t.get("pnl") is not None]
        r_multiples = [float(t.get("r_multiple", 0)) for t in trades if t.get("r_multiple") is not None]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = (len(wins) / len(pnls) * 100) if pnls else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        avg_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0
        total_pnl = sum(pnls)

        return {
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_r_multiple": round(avg_r, 3),
            "daily_pnl": round(total_pnl / days, 2) if days else 0.0,
            "total_pnl": round(total_pnl, 2),
            "total_trades": len(trades),
            "window_days": days,
        }

    async def _all_time(self) -> Dict[str, Any]:
        if self._db is None:
            return {"total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "total_pnl": 0.0}

        try:
            cursor = self._db.trades.find(
                {"status": {"$in": ["closed", "CLOSED"]}},
                {"pnl": 1, "r_multiple": 1, "_id": 0},
            )
            trades = await cursor.to_list(length=10000)
        except Exception as e:
            logger.warning(f"PerformanceTracker all_time fetch error: {e}")
            return {"total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "total_pnl": 0.0}

        if not trades:
            return {"total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "total_pnl": 0.0}

        pnls = [float(t.get("pnl", 0)) for t in trades if t.get("pnl") is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = (len(wins) / len(pnls) * 100) if pnls else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "total_pnl": round(sum(pnls), 2),
        }

    async def _equity_curve(self, end: datetime, days: int) -> List[Dict[str, Any]]:
        start = end - timedelta(days=days)
        trades = await self._fetch_trades(start, end)

        if not trades:
            return []

        sorted_trades = sorted(trades, key=lambda t: t.get("saved_at", 0))
        equity = 10_000.0
        curve = [{"ts": start.isoformat(), "equity": equity}]

        for t in sorted_trades:
            equity += float(t.get("pnl", 0))
            ts_raw = t.get("saved_at") or t.get("closed_at") or t.get("timestamp")
            ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if isinstance(ts_raw, (int, float)) else str(ts_raw)
            curve.append({"ts": ts, "equity": round(equity, 2)})

        return curve

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _fetch_trades(self, start: datetime, end: datetime) -> List[Dict]:
        if self._db is None:
            return []

        start_ts = start.timestamp()
        end_ts = end.timestamp()

        try:
            cursor = self._db.trades.find(
                {
                    "status": {"$in": ["closed", "CLOSED"]},
                    "saved_at": {"$gte": start_ts, "$lte": end_ts},
                },
                {"pnl": 1, "r_multiple": 1, "saved_at": 1, "closed_at": 1, "symbol": 1, "_id": 0},
            )
            return await cursor.to_list(length=5000)
        except Exception as e:
            logger.warning(f"PerformanceTracker fetch error: {e}")
            return []

    @staticmethod
    def _drawdown_from_curve(curve: List[Dict]) -> float:
        if not curve:
            return 0.0

        peak = curve[0]["equity"]
        max_dd = 0.0
        for pt in curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100
                max_dd = max(max_dd, dd)

        return round(max_dd, 2)

    def _check_alerts(self, metrics: Dict, drawdown: float) -> List[Dict]:
        alerts = []
        now_iso = datetime.now(timezone.utc).isoformat()

        if (
            metrics["total_trades"] >= self.MIN_TRADES_FOR_ALERTS
            and metrics["win_rate"] < self.WIN_RATE_ALERT_THRESHOLD
        ):
            alerts.append({
                "type": "win_rate_degradation",
                "severity": "warning",
                "message": f"Win rate {metrics['win_rate']:.1f}% below threshold {self.WIN_RATE_ALERT_THRESHOLD}%",
                "timestamp": now_iso,
            })
            logger.warning(f"[PerfTracker] Win rate alert: {metrics['win_rate']:.1f}%")

        if drawdown > self.DRAWDOWN_ALERT_THRESHOLD:
            alerts.append({
                "type": "drawdown_exceeded",
                "severity": "critical",
                "message": f"Drawdown {drawdown:.1f}% exceeds threshold {self.DRAWDOWN_ALERT_THRESHOLD}%",
                "timestamp": now_iso,
            })
            logger.critical(f"[PerfTracker] Drawdown alert: {drawdown:.1f}%")

        return alerts
