"""Analyze long vs short trade performance from MongoDB."""
import asyncio
import motor.motor_asyncio


async def analyze():
    client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["moonshot"]

    trades = await db.trades.find(
        {"pnl_usd": {"$exists": True}, "trading_mode": "futures"},
        {"_id": 0, "symbol": 1, "direction": 1, "pnl_usd": 1, "pnl_pct": 1,
         "exit_reason": 1, "setup_type": 1},
    ).sort("saved_at", -1).to_list(500)

    longs = [t for t in trades if t.get("direction") == "long"]
    shorts = [t for t in trades if t.get("direction") == "short"]

    def stats(label, tlist):
        if not tlist:
            print(f"{label}: 0 trades")
            return
        wins = [t for t in tlist if (t.get("pnl_usd") or 0) > 0]
        losses = [t for t in tlist if (t.get("pnl_usd") or 0) <= 0]
        total_pnl = sum(t.get("pnl_usd", 0) for t in tlist)
        avg_win = sum(t.get("pnl_usd", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("pnl_usd", 0) for t in losses) / len(losses) if losses else 0
        wr = len(wins) / len(tlist) * 100
        print(f"\n=== {label} ({len(tlist)} trades) ===")
        print(f"Win rate: {wr:.0f}% ({len(wins)}W / {len(losses)}L)")
        print(f"Total PnL: ${total_pnl:.2f}")
        print(f"Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")
        by_pnl = sorted(tlist, key=lambda x: x.get("pnl_usd", 0))
        print("Worst 3:")
        for t in by_pnl[:3]:
            sym = t.get("symbol", "?")
            pnl = t.get("pnl_usd", 0)
            ex = t.get("exit_reason", "?")
            print(f"  {sym:25s} ${pnl:>8.2f}  exit={ex}")
        print("Best 3:")
        for t in by_pnl[-3:]:
            sym = t.get("symbol", "?")
            pnl = t.get("pnl_usd", 0)
            ex = t.get("exit_reason", "?")
            print(f"  {sym:25s} ${pnl:>8.2f}  exit={ex}")
        reasons = {}
        for t in tlist:
            r = t.get("exit_reason", "unknown")
            if r not in reasons:
                reasons[r] = {"count": 0, "pnl": 0.0}
            reasons[r]["count"] += 1
            reasons[r]["pnl"] += t.get("pnl_usd", 0)
        print("Exit reasons:")
        for r, d in sorted(reasons.items(), key=lambda x: x[1]["pnl"]):
            print(f"  {r:25s} {d['count']:>3d}x  PnL=${d['pnl']:>8.2f}")

    stats("LONGS", longs)
    stats("SHORTS", shorts)
    stats("ALL", trades)


asyncio.run(analyze())
