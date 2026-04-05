#!/usr/bin/env python3
"""Deep trade analysis — run on VM with: .venv/bin/python3 scripts/analyze_trades.py"""
import asyncio
import json
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict
from datetime import datetime, timezone


async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["apex_swarm"]

    trades = []
    async for t in db.trades.find().sort("saved_at", 1):
        if t.get("type") == "partial":
            continue
        trades.append(t)

    total = len(trades)
    if total == 0:
        print("No trades found.")
        return

    wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
    losses = [t for t in trades if t.get("pnl_usd", 0) < 0]
    breakeven = [t for t in trades if t.get("pnl_usd", 0) == 0]

    total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
    avg_win = sum(t.get("pnl_usd", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl_usd", 0) for t in losses) / len(losses) if losses else 0
    max_win = max((t.get("pnl_usd", 0) for t in wins), default=0)
    max_loss = min((t.get("pnl_usd", 0) for t in losses), default=0)

    print(f"=== OVERALL STATS ({total} trades) ===")
    print(f"Wins: {len(wins)} ({len(wins)/total*100:.0f}%)")
    print(f"Losses: {len(losses)} ({len(losses)/total*100:.0f}%)")
    print(f"Breakeven: {len(breakeven)}")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Avg win: ${avg_win:.2f}  Avg loss: ${avg_loss:.2f}")
    print(f"Max win: ${max_win:.2f}  Max loss: ${max_loss:.2f}")
    if wins:
        print(f"Avg hold (wins): {sum(t.get('hold_time_hours',0) for t in wins)/len(wins):.2f}h")
    if losses:
        print(f"Avg hold (losses): {sum(t.get('hold_time_hours',0) for t in losses)/len(losses):.2f}h")

    # By exit reason
    print(f"\n=== BY EXIT REASON ===")
    by_reason = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        r = t.get("close_reason", "?")
        by_reason[r]["count"] += 1
        by_reason[r]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            by_reason[r]["wins"] += 1
    for r, d in sorted(by_reason.items(), key=lambda x: x[1]["pnl"]):
        wr = d["wins"] / d["count"] * 100 if d["count"] else 0
        print(f"  {r:45s} n={d['count']:3d}  PnL=${d['pnl']:+9.2f}  WR={wr:.0f}%")

    # By regime
    print(f"\n=== BY REGIME ===")
    by_regime = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        r = t.get("regime", "?")
        by_regime[r]["count"] += 1
        by_regime[r]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            by_regime[r]["wins"] += 1
    for r, d in sorted(by_regime.items(), key=lambda x: x[1]["pnl"]):
        wr = d["wins"] / d["count"] * 100 if d["count"] else 0
        print(f"  {r:20s} n={d['count']:3d}  PnL=${d['pnl']:+9.2f}  WR={wr:.0f}%")

    # By setup type
    print(f"\n=== BY SETUP TYPE ===")
    by_setup = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        s = t.get("setup_type", "?")
        by_setup[s]["count"] += 1
        by_setup[s]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            by_setup[s]["wins"] += 1
    for s, d in sorted(by_setup.items(), key=lambda x: x[1]["pnl"]):
        wr = d["wins"] / d["count"] * 100 if d["count"] else 0
        print(f"  {s:30s} n={d['count']:3d}  PnL=${d['pnl']:+9.2f}  WR={wr:.0f}%")

    # Chronological phases
    print(f"\n=== CHRONOLOGICAL PHASES (5-trade windows) ===")
    for i in range(0, total, 5):
        batch = trades[i : i + 5]
        batch_pnl = sum(t.get("pnl_usd", 0) for t in batch)
        batch_wins = sum(1 for t in batch if t.get("pnl_usd", 0) > 0)
        ts = batch[0].get("saved_at", 0)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b%d %H:%M")
        regimes = set(t.get("regime", "?") for t in batch)
        reasons = [t.get("close_reason", "?")[:15] for t in batch]
        avg_margin = sum(t.get("margin_usd", 0) for t in batch) / len(batch)
        print(
            f"  {dt} | #{i+1:3d}-{min(i+5,total):3d} | PnL=${batch_pnl:+9.2f} | "
            f"W={batch_wins}/{len(batch)} | regime={regimes} | avg_margin=${avg_margin:.0f} | "
            f"exits={reasons}"
        )

    # By leverage
    print(f"\n=== BY LEVERAGE ===")
    by_lev = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        lev = t.get("leverage", 1)
        by_lev[lev]["count"] += 1
        by_lev[lev]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            by_lev[lev]["wins"] += 1
    for l, d in sorted(by_lev.items()):
        wr = d["wins"] / d["count"] * 100 if d["count"] else 0
        print(f"  {l}x: n={d['count']:3d}  PnL=${d['pnl']:+9.2f}  WR={wr:.0f}%")

    # Position size analysis
    print(f"\n=== POSITION SIZE vs OUTCOME ===")
    small = [t for t in trades if t.get("margin_usd", 0) < 200]
    medium = [t for t in trades if 200 <= t.get("margin_usd", 0) < 500]
    large = [t for t in trades if t.get("margin_usd", 0) >= 500]
    for label, group in [
        ("Small <$200", small),
        ("Medium $200-500", medium),
        ("Large >$500", large),
    ]:
        if not group:
            continue
        g_pnl = sum(t.get("pnl_usd", 0) for t in group)
        g_wins = sum(1 for t in group if t.get("pnl_usd", 0) > 0)
        wr = g_wins / len(group) * 100
        print(f"  {label:20s} n={len(group):3d}  PnL=${g_pnl:+9.2f}  WR={wr:.0f}%")

    # Top 5 winners and losers
    print(f"\n=== TOP 5 WINNERS ===")
    for t in sorted(trades, key=lambda x: x.get("pnl_usd", 0), reverse=True)[:5]:
        sym = t.get("symbol", "?")
        pnl = t.get("pnl_usd", 0)
        pct = t.get("pnl_pct", 0)
        hold = t.get("hold_time_hours", 0)
        lev = t.get("leverage", 1)
        margin = t.get("margin_usd", 0)
        reason = t.get("close_reason", "?")
        print(f"  {sym:25s} ${pnl:+9.2f} ({pct:+.1f}%) hold={hold:.2f}h lev={lev}x margin=${margin:.0f} exit={reason}")

    print(f"\n=== TOP 5 LOSERS ===")
    for t in sorted(trades, key=lambda x: x.get("pnl_usd", 0))[:5]:
        sym = t.get("symbol", "?")
        pnl = t.get("pnl_usd", 0)
        pct = t.get("pnl_pct", 0)
        hold = t.get("hold_time_hours", 0)
        lev = t.get("leverage", 1)
        margin = t.get("margin_usd", 0)
        reason = t.get("close_reason", "?")
        print(f"  {sym:25s} ${pnl:+9.2f} ({pct:+.1f}%) hold={hold:.2f}h lev={lev}x margin=${margin:.0f} exit={reason}")

    # The money-printing period analysis
    print(f"\n=== MONEY-PRINTING vs BLEEDING ANALYSIS ===")
    cumulative = 0
    peak = 0
    peak_idx = 0
    for i, t in enumerate(trades):
        cumulative += t.get("pnl_usd", 0)
        if cumulative > peak:
            peak = cumulative
            peak_idx = i
    
    print(f"Peak cumulative PnL: ${peak:.2f} at trade #{peak_idx+1}")
    
    # Split into before peak and after peak
    before = trades[:peak_idx+1]
    after = trades[peak_idx+1:]
    
    if before:
        b_pnl = sum(t.get("pnl_usd", 0) for t in before)
        b_wins = sum(1 for t in before if t.get("pnl_usd", 0) > 0)
        b_avg_margin = sum(t.get("margin_usd", 0) for t in before) / len(before)
        b_regimes = defaultdict(int)
        b_reasons = defaultdict(int)
        for t in before:
            b_regimes[t.get("regime", "?")] += 1
            b_reasons[t.get("close_reason", "?")] += 1
        print(f"\nBEFORE PEAK (trades 1-{peak_idx+1}, the 'money printer' phase):")
        print(f"  Trades: {len(before)}  PnL: ${b_pnl:.2f}  WR: {b_wins/len(before)*100:.0f}%  Avg margin: ${b_avg_margin:.0f}")
        print(f"  Regimes: {dict(b_regimes)}")
        print(f"  Exit reasons: {dict(b_reasons)}")
        b_avg_win = sum(t.get("pnl_usd", 0) for t in before if t.get("pnl_usd", 0) > 0) / max(b_wins, 1)
        b_losses = [t for t in before if t.get("pnl_usd", 0) < 0]
        b_avg_loss = sum(t.get("pnl_usd", 0) for t in b_losses) / max(len(b_losses), 1)
        print(f"  Avg win: ${b_avg_win:.2f}  Avg loss: ${b_avg_loss:.2f}")
    
    if after:
        a_pnl = sum(t.get("pnl_usd", 0) for t in after)
        a_wins = sum(1 for t in after if t.get("pnl_usd", 0) > 0)
        a_avg_margin = sum(t.get("margin_usd", 0) for t in after) / len(after)
        a_regimes = defaultdict(int)
        a_reasons = defaultdict(int)
        for t in after:
            a_regimes[t.get("regime", "?")] += 1
            a_reasons[t.get("close_reason", "?")] += 1
        print(f"\nAFTER PEAK (trades {peak_idx+2}-{total}, the 'bleeding' phase):")
        print(f"  Trades: {len(after)}  PnL: ${a_pnl:.2f}  WR: {a_wins/len(after)*100:.0f}%  Avg margin: ${a_avg_margin:.0f}")
        print(f"  Regimes: {dict(a_regimes)}")
        print(f"  Exit reasons: {dict(a_reasons)}")
        a_winners = [t for t in after if t.get("pnl_usd", 0) > 0]
        a_avg_win = sum(t.get("pnl_usd", 0) for t in a_winners) / max(len(a_winners), 1)
        a_losers = [t for t in after if t.get("pnl_usd", 0) < 0]
        a_avg_loss = sum(t.get("pnl_usd", 0) for t in a_losers) / max(len(a_losers), 1)
        print(f"  Avg win: ${a_avg_win:.2f}  Avg loss: ${a_avg_loss:.2f}")


asyncio.run(main())
