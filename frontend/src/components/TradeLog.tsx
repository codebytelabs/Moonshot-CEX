"use client";

interface Trade {
  id?: string;
  symbol: string;
  close_reason?: string;
  pnl_usd?: number;
  pnl_pct?: number;
  entry_price?: number;
  exit_price?: number;
  hold_time_hours?: number;
  setup_type?: string;
  closed_at?: number;
}

interface Props {
  trades: unknown[];
}

export default function TradeLog({ trades }: Props) {
  const tradeList = trades as Trade[];

  const getSide = (t: Trade): "buy" | "sell" | "close" => {
    const r = (t.close_reason ?? "").toLowerCase();
    if (r === "buy") return "buy";
    if (r === "sell") return "sell";
    return "close";
  };

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0 flex items-center justify-between">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Trade History</span>
        <span className="text-[10px] mono text-slate-600">{tradeList.length} trades</span>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {tradeList.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-700">
            <span className="text-2xl">📋</span>
            <span className="text-[10px] mono mt-1">No completed trades yet</span>
          </div>
        ) : (
          <table className="w-full text-[10px] mono">
            <thead>
              <tr className="border-b border-white/5">
                {["Symbol", "Side", "PnL", "%", "Setup", "Hold"].map((h) => (
                  <th key={h} className="text-left px-2 py-1.5 text-slate-600 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tradeList.slice().reverse().map((t, i) => {
                const pnl = t.pnl_usd ?? 0;
                const pct = t.pnl_pct ?? 0;
                const win = pnl >= 0;
                const side = getSide(t);
                const isBuy = side === "buy";
                const isSell = side === "sell";
                const rowBg = isBuy
                  ? "border-b border-white/3 hover:bg-cyan-950/20 bg-cyan-950/10"
                  : isSell
                  ? "border-b border-white/3 hover:bg-rose-950/20 bg-rose-950/10"
                  : "border-b border-white/3 hover:bg-white/2";
                return (
                  <tr key={t.id ?? i} className={rowBg}>
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        <div className={`w-1 h-3 rounded-sm ${isBuy ? "bg-cyan-400" : isSell ? "bg-rose-400" : win ? "bg-green-400" : "bg-red-400"}`} />
                        <span className="text-slate-300">{t.symbol}</span>
                      </div>
                    </td>
                    <td className="px-2 py-1.5">
                      {isBuy ? (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">BUY</span>
                      ) : isSell ? (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/20">SELL</span>
                      ) : (
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${win ? "bg-green-500/15 text-green-400 border border-green-500/20" : "bg-red-500/15 text-red-400 border border-red-500/20"}`}>
                          {(t.close_reason ?? "exit").replace(/_/g, " ").toUpperCase()}
                        </span>
                      )}
                    </td>
                    <td className={`px-2 py-1.5 font-semibold ${win ? "text-green-400" : pnl < 0 ? "text-red-400" : "text-slate-400"}`}>
                      {pnl !== 0 ? (win ? "+" : "") + "$" + pnl.toFixed(2) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className={`px-2 py-1.5 ${win ? "text-green-400" : pnl < 0 ? "text-red-400" : "text-slate-600"}`}>
                      {pnl !== 0 ? (win ? "+" : "") + pct.toFixed(1) + "%" : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500">{t.setup_type ?? "-"}</td>
                    <td className="px-2 py-1.5 text-slate-600">{(t.hold_time_hours ?? 0).toFixed(1)}h</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
