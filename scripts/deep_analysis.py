#!/usr/bin/env python3
"""Deep winner/loser analysis for strategy redesign."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict


async def main():
    db = AsyncIOMotorClient("mongodb://localhost:27017")["apex_swarm"]
    trades = await db.trades.find({"status": "closed"}).to_list(500)

    ts_wins = [t for t in trades if "trailing_stop" in t.get("close_reason", "") and t.get("pnl_usd", 0) > 0]
    sl_losses = [t for t in trades if "stop_loss" in t.get("close_reason", "") and t.get("pnl_usd", 0) < 0]
    eti_losses = [t for t in trades if t.get("close_reason", "") == "early_thesis_invalid"]

    print("=== TRAILING STOP WINNERS (what works) ===")
    print(f"Count: {len(ts_wins)}")
    if ts_wins:
        syms = defaultdict(lambda: {"cnt": 0, "pnl": 0.0})
        for t in ts_wins:
            s = t.get("symbol", "?")
            syms[s]["cnt"] += 1
            syms[s]["pnl"] += t.get("pnl_usd", 0)
        print("Top winning symbols:")
        for s, d in sorted(syms.items(), key=lambda x: -x[1]["pnl"])[:10]:
            print(f"  {s}: {d['cnt']} wins, PnL=+${d['pnl']:.2f}")

    print()
    print("=== EARLY THESIS INVALID ===")
    print(f"Count: {len(eti_losses)}")
    if eti_losses:
        avg_pnl = sum(t.get("pnl_usd", 0) for t in eti_losses) / len(eti_losses)
        avg_hold = sum(t.get("hold_time_hours", 0) for t in eti_losses) / len(eti_losses)
        setups = defaultdict(int)
        for t in eti_losses:
            setups[t.get("setup_type", "?")] += 1
        recovered = sum(
            1 for t in eti_losses
            if t.get("highest_price", 0) > t.get("entry_price", 0) * 1.005
        )
        print(f"Avg PnL: ${avg_pnl:.2f} | Avg hold: {avg_hold:.2f}h")
        print(f"Setups: {dict(setups)}")
        print(f"Would have recovered +0.5%: {recovered}/{len(eti_losses)}")

    # By symbol: which symbols are net positive?
    print()
    print("=== NET PNL BY SYMBOL (top/bottom) ===")
    sym_pnl = defaultdict(lambda: {"cnt": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        s = t.get("symbol", "?")
        sym_pnl[s]["cnt"] += 1
        sym_pnl[s]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            sym_pnl[s]["wins"] += 1

    sorted_syms = sorted(sym_pnl.items(), key=lambda x: x[1]["pnl"])
    print("WORST 10:")
    for s, d in sorted_syms[:10]:
        wr = d["wins"] / d["cnt"] * 100 if d["cnt"] else 0
        print(f"  {s:25s} n={d['cnt']:2d} PnL=${d['pnl']:+8.2f} WR={wr:.0f}%")
    print("BEST 10:")
    for s, d in sorted_syms[-10:]:
        wr = d["wins"] / d["cnt"] * 100 if d["cnt"] else 0
        print(f"  {s:25s} n={d['cnt']:2d} PnL=${d['pnl']:+8.2f} WR={wr:.0f}%")

    # Win rate by posterior confidence
    print()
    print("=== WIN RATE BY POSTERIOR CONFIDENCE ===")
    bins = [(0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    for lo, hi in bins:
        group = [t for t in trades if lo <= t.get("posterior", 0) < hi]
        if not group:
            continue
        wins = sum(1 for t in group if t.get("pnl_usd", 0) > 0)
        pnl = sum(t.get("pnl_usd", 0) for t in group)
        wr = wins / len(group) * 100
        print(f"  posterior {lo:.1f}-{hi:.1f}: n={len(group):3d} WR={wr:.0f}% PnL=${pnl:+.2f}")

    # Win rate by hold time
    print()
    print("=== WIN RATE BY HOLD TIME ===")
    tbins = [(0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 10.0)]
    for lo, hi in tbins:
        group = [t for t in trades if lo <= t.get("hold_time_hours", 0) < hi]
        if not group:
            continue
        wins = sum(1 for t in group if t.get("pnl_usd", 0) > 0)
        pnl = sum(t.get("pnl_usd", 0) for t in group)
        wr = wins / len(group) * 100
        print(f"  hold {lo:.1f}-{hi:.1f}h: n={len(group):3d} WR={wr:.0f}% PnL=${pnl:+.2f}")

    # Time exit trades — how many were actually profitable at peak?
    print()
    print("=== TIME EXIT ANALYSIS ===")
    te = [t for t in trades if t.get("close_reason", "").startswith("time_exit")]
    if te:
        had_profit = sum(1 for t in te if t.get("highest_price", 0) > t.get("entry_price", 0) * 1.01)
        print(f"Count: {len(te)}")
        print(f"Had +1% unrealized at some point: {had_profit}/{len(te)}")
        avg_pnl = sum(t.get("pnl_usd", 0) for t in te) / len(te)
        print(f"Avg exit PnL: ${avg_pnl:.2f}")

    # Regime + setup cross-tab
    print()
    print("=== REGIME x SETUP CROSS-TAB (PnL) ===")
    regimes = sorted(set(t.get("regime", "?") for t in trades))
    setups = sorted(set(t.get("setup_type", "?") for t in trades))
    header = f"{'':20s}" + "".join(f"{r:>12s}" for r in regimes) + f"{'TOTAL':>12s}"
    print(header)
    for s in setups:
        row = f"{s:20s}"
        total = 0
        for r in regimes:
            group = [t for t in trades if t.get("setup_type") == s and t.get("regime") == r]
            pnl = sum(t.get("pnl_usd", 0) for t in group)
            total += pnl
            row += f"${pnl:+10.0f}  " if group else f"{'--':>12s}"
            
        row += f"${total:+10.0f}"
        print(row)


asyncio.run(main())
