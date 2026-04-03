#!/usr/bin/env python3
"""
Moonshot-CEX Backtester
=======================
Replays historical OHLCV data through the Watcher → Analyzer → Bayesian pipeline
to validate strategy changes before live deployment.

Usage:
    python scripts/backtest.py --symbol SOL/USDT --days 30
    python scripts/backtest.py --symbols BTC/USDT ETH/USDT SOL/USDT --days 14 --tf 15m

The backtester uses a simplified paper-trading engine that mirrors the live bot's
entry/exit logic (stop loss, tier exits, trailing stop, time exit).
"""
import argparse
import asyncio
import sys
import os
from dataclasses import dataclass, field
from typing import Optional

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import Settings
from src.exchange_ccxt import ExchangeConnector


# ── Config ────────────────────────────────────────────────────────────────────

cfg = Settings()

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    symbol: str
    entry_price: float
    entry_bar: int
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    amount_usd: float = 100.0
    amount: float = 0.0
    tier1_done: bool = False
    tier2_done: bool = False
    realized_pnl: float = 0.0
    exit_price: float = 0.0
    exit_bar: int = 0
    close_reason: str = ""
    hold_bars: int = 0
    pnl_pct: float = 0.0

    def __post_init__(self):
        if self.entry_price > 0:
            self.amount = self.amount_usd / self.entry_price


@dataclass
class BacktestResult:
    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    trades: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / max(self.total_trades, 1)

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / max(abs(self.gross_loss), 0.01)

    @property
    def avg_win(self) -> float:
        wins = [t.realized_pnl for t in self.trades if t.realized_pnl > 0]
        return sum(wins) / max(len(wins), 1)

    @property
    def avg_loss(self) -> float:
        losses = [t.realized_pnl for t in self.trades if t.realized_pnl <= 0]
        return sum(losses) / max(len(losses), 1)


# ── Paper trading engine ───────────────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> float:
    """Simple EMA of last `period` values."""
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def _compute_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period or 1e-9
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _score_candle(candles: list, idx: int) -> tuple[float, bool]:
    """Score a single entry candle. Returns (score, should_enter)."""
    window = candles[max(0, idx - 60): idx + 1]
    if len(window) < 30:
        return 0.0, False

    closes = [c[4] for c in window]
    volumes = [c[5] for c in window]

    # Volume spike
    avg_vol = sum(volumes[-20:]) / 20
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    # RSI
    rsi = _compute_rsi(closes, 14)

    # EMA alignment
    ema9 = _ema(closes[-9:], 9)
    ema21 = _ema(closes[-21:], 21)

    # Simple momentum: 3 last bars green
    green = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])

    score = (
        min(60.0, vol_ratio * 15.0)
        + (15.0 if 55 <= rsi <= 75 else 0.0)
        + (8.0 if ema9 > ema21 else 0.0)
        + green * 6.0
    )
    return score, score >= 35.0


def _simulate_trade(
    candles: list,
    entry_bar: int,
    symbol: str,
    sl_pct: float = -5.0,
    tier1_r: float = 2.0,
    tier2_r: float = 5.0,
    time_exit_bars: int = 48,
    position_usd: float = 100.0,
) -> BacktestTrade:
    """Simulate a single trade from entry_bar to close."""
    entry_c = candles[entry_bar]
    entry_price = entry_c[4]  # close price

    risk_per_unit = entry_price * abs(sl_pct) / 100.0
    stop_loss = entry_price - risk_per_unit
    take_profit_1 = entry_price + tier1_r * risk_per_unit
    take_profit_2 = entry_price + tier2_r * risk_per_unit

    trade = BacktestTrade(
        symbol=symbol,
        entry_price=entry_price,
        entry_bar=entry_bar,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        amount_usd=position_usd,
    )

    highest = entry_price
    trailing_stop: Optional[float] = None

    for i in range(entry_bar + 1, min(entry_bar + time_exit_bars + 1, len(candles))):
        bar = candles[i]
        low, high, close = bar[3], bar[2], bar[4]

        if high > highest:
            highest = high
            # Activate trailing stop at 15% gain
            if (highest - entry_price) / entry_price >= 0.15:
                trailing_stop = highest * 0.92  # 8% trail

        # Stop loss hit (use low to detect intrabar)
        if low <= stop_loss:
            exit_p = stop_loss
            trade.realized_pnl = (exit_p - entry_price) * trade.amount
            if trade.tier1_done:
                trade.realized_pnl += (take_profit_1 - entry_price) * trade.amount * 0.25
            trade.exit_price = exit_p
            trade.exit_bar = i
            trade.close_reason = "stop_loss"
            break

        # Trailing stop hit
        if trailing_stop and low <= trailing_stop:
            exit_p = trailing_stop
            trade.realized_pnl = (exit_p - entry_price) * trade.amount
            if trade.tier1_done:
                trade.realized_pnl += (take_profit_1 - entry_price) * trade.amount * 0.25
            trade.exit_price = exit_p
            trade.exit_bar = i
            trade.close_reason = "trailing_stop"
            break

        # Tier 1
        if not trade.tier1_done and high >= take_profit_1:
            trade.tier1_done = True
            trade.realized_pnl += (take_profit_1 - entry_price) * trade.amount * 0.25

        # Tier 2
        if trade.tier1_done and not trade.tier2_done and high >= take_profit_2:
            trade.tier2_done = True
            trade.realized_pnl += (take_profit_2 - entry_price) * trade.amount * 0.25
            # Close rest at take profit 2
            trade.exit_price = take_profit_2
            trade.exit_bar = i
            trade.close_reason = "take_profit_2"
            trade.realized_pnl += (take_profit_2 - entry_price) * trade.amount * 0.5
            break

        # Time exit
        if i == entry_bar + time_exit_bars:
            trade.realized_pnl += (close - entry_price) * trade.amount * (0.5 if trade.tier1_done else 1.0)
            if trade.tier1_done:
                trade.realized_pnl += (close - entry_price) * trade.amount * 0.25
            trade.exit_price = close
            trade.exit_bar = i
            trade.close_reason = "time_exit"
            break

    trade.hold_bars = trade.exit_bar - trade.entry_bar
    trade.pnl_pct = trade.realized_pnl / position_usd * 100.0 if position_usd > 0 else 0.0
    return trade


def _backtest_symbol(candles: list, symbol: str, args) -> BacktestResult:
    result = BacktestResult(symbol=symbol)
    in_trade = False
    equity = 1000.0
    peak_equity = equity

    for i in range(60, len(candles) - 1):
        if in_trade:
            continue
        score, should_enter = _score_candle(candles, i)
        if not should_enter:
            continue

        trade = _simulate_trade(
            candles, i, symbol,
            sl_pct=args.sl_pct,
            tier1_r=args.tier1_r,
            tier2_r=args.tier2_r,
            time_exit_bars=args.time_exit_bars,
            position_usd=equity * 0.1,
        )

        if trade.exit_bar == 0:  # never closed (end of data)
            continue

        result.total_trades += 1
        result.trades.append(trade)

        equity += trade.realized_pnl
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity
        result.max_drawdown = max(result.max_drawdown, dd)

        if trade.realized_pnl > 0:
            result.wins += 1
            result.gross_profit += trade.realized_pnl
        else:
            result.losses += 1
            result.gross_loss += trade.realized_pnl

        result.total_pnl = equity - 1000.0
        i = trade.exit_bar + 1  # skip to after trade

    return result


def _print_result(r: BacktestResult):
    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  {r.symbol}  —  {r.total_trades} trades")
    print(sep)
    print(f"  Win Rate:       {r.win_rate:.1%}")
    print(f"  Profit Factor:  {r.profit_factor:.2f}")
    print(f"  Total PnL:      ${r.total_pnl:+.2f} ({r.total_pnl/10:.1f}% of $1000)")
    print(f"  Max Drawdown:   {r.max_drawdown:.1%}")
    print(f"  Avg Win:        ${r.avg_win:+.2f}")
    print(f"  Avg Loss:       ${r.avg_loss:+.2f}")
    print(f"  Wins/Losses:    {r.wins} / {r.losses}")
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Moonshot-CEX Backtester")
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    parser.add_argument("--days", type=int, default=30, help="Days of history to test")
    parser.add_argument("--tf", default="15m", help="Timeframe (5m, 15m, 1h)")
    parser.add_argument("--sl-pct", type=float, default=-5.0, help="Stop loss %")
    parser.add_argument("--tier1-r", type=float, default=2.0, help="Tier1 R multiple")
    parser.add_argument("--tier2-r", type=float, default=5.0, help="Tier2 R multiple")
    parser.add_argument("--time-exit-bars", type=int, default=48, help="Max bars before time exit")
    args = parser.parse_args()

    # Map timeframe → bars per day
    tf_bars = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6}
    bars_per_day = tf_bars.get(args.tf, 96)
    limit = min(args.days * bars_per_day, 1000)

    print(f"\n🔬 Moonshot-CEX Backtester")
    print(f"   Timeframe: {args.tf}  |  Days: {args.days}  |  Bars: {limit}")
    print(f"   SL: {args.sl_pct}%  Tier1: {args.tier1_r}R  Tier2: {args.tier2_r}R")
    print(f"   Symbols: {', '.join(args.symbols)}\n")

    exchange = ExchangeConnector(
        exchange_id=cfg.exchange_name,
        api_key=cfg.exchange_api_key,
        api_secret=cfg.exchange_api_secret,
        sandbox=True,
        exchange_mode="paper",
    )

    try:
        await exchange.load_markets()
    except Exception as e:
        print(f"⚠️  Exchange connect failed: {e}")
        print("   Running in offline simulation mode with synthetic data...\n")
        exchange = None

    all_results = []

    for symbol in args.symbols:
        print(f"  Fetching {symbol} [{args.tf} × {limit} bars]...", end=" ", flush=True)
        try:
            if exchange:
                candles = await exchange.fetch_ohlcv(symbol, args.tf, limit=limit)
            else:
                # Synthetic random-walk data for offline testing
                import random
                price = 100.0
                candles = []
                for _ in range(limit):
                    o = price
                    h = o * (1 + random.uniform(0, 0.03))
                    l = o * (1 - random.uniform(0, 0.02))
                    c = random.uniform(l, h)
                    v = random.uniform(1000, 50000)
                    candles.append([0, o, h, l, c, v])
                    price = c
            print(f"✅ {len(candles)} bars")
        except Exception as e:
            print(f"❌ {e}")
            continue

        result = _backtest_symbol(candles, symbol, args)
        all_results.append(result)
        _print_result(result)

    # Aggregate summary
    if all_results:
        print("\n" + "═" * 52)
        print("  AGGREGATE SUMMARY")
        print("═" * 52)
        total_trades = sum(r.total_trades for r in all_results)
        total_wins = sum(r.wins for r in all_results)
        total_pnl = sum(r.total_pnl for r in all_results)
        gross_p = sum(r.gross_profit for r in all_results)
        gross_l = abs(sum(r.gross_loss for r in all_results)) or 0.01
        print(f"  Total Trades:   {total_trades}")
        print(f"  Win Rate:       {total_wins / max(total_trades, 1):.1%}")
        print(f"  Profit Factor:  {gross_p / gross_l:.2f}")
        print(f"  Total PnL:      ${total_pnl:+.2f}")
        print("═" * 52)

    if exchange:
        try:
            await exchange.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
