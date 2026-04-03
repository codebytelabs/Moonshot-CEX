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

const EXCHANGE_NOISE = new Set(["exchange_sell", "exchange_fill", "exchange_buy"]);
const DUST_REASONS = new Set(["stop_loss_dust", "trailing_stop_dust", "closed_dust", "closed_on_restart", "closed_cb_cleanup"]);

function getReasonBadge(reason: string, win: boolean) {
  const r = reason.toLowerCase();
  if (r.startsWith("tp") || r === "take_profit")
    return { label: reason.toUpperCase().replace(/_/g, ""), cls: "bg-green-500/15 text-green-400 border-green-500/20" };
  if (r === "stop_loss" || r === "stoploss")
    return { label: "STOP LOSS", cls: "bg-red-500/15 text-red-400 border-red-500/20" };
  if (r.includes("trailing"))
    return { label: "TRAIL", cls: "bg-teal-500/15 text-teal-400 border-teal-500/20" };
  if (r.includes("momentum"))
    return { label: "MOMENTUM", cls: "bg-sky-500/15 text-sky-400 border-sky-500/20" };
  if (r.includes("time"))
    return { label: "TIME", cls: "bg-amber-500/15 text-amber-400 border-amber-500/20" };
  if (r.includes("regime") || r.includes("sweep"))
    return { label: "REGIME", cls: "bg-orange-500/15 text-orange-400 border-orange-500/20" };
  if (r.includes("ghost"))
    return { label: "GHOST", cls: "bg-slate-500/15 text-slate-400 border-slate-500/20" };
  if (r.includes("emergency"))
    return { label: "EMERGENCY", cls: "bg-red-600/20 text-red-300 border-red-600/30" };
  return {
    label: reason.replace(/_/g, " ").toUpperCase().slice(0, 12),
    cls: win ? "bg-green-500/15 text-green-400 border-green-500/20" : "bg-red-500/15 text-red-400 border-red-500/20",
  };
}

export default function TradeLog({ trades }: Props) {
  const raw = trades as Trade[];
  // Filter out exchange sync noise — show only actual bot-initiated closes
  const tradeList = raw.filter((t) => {
    const reason = (t.close_reason ?? "").toLowerCase();
    return !EXCHANGE_NOISE.has(reason) && !DUST_REASONS.has(reason);
  });

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
                {["Symbol", "Exit", "Entry", "Exit Px", "PnL", "%", "Setup", "Hold"].map((h) => (
                  <th key={h} className="text-left px-2 py-1.5 text-slate-600 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tradeList.slice().sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).map((t, i) => {
                const pnl = t.pnl_usd ?? 0;
                const pct = t.pnl_pct ?? 0;
                const win = pnl >= 0;
                const reason = t.close_reason ?? "exit";
                const badge = getReasonBadge(reason, win);
                return (
                  <tr key={t.id ?? i} className="border-b border-white/3 hover:bg-white/2">
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        <div className={`w-1 h-3 rounded-sm ${win ? "bg-green-400" : "bg-red-400"}`} />
                        <span className="text-slate-300">{t.symbol?.replace("/USDT", "")}</span>
                      </div>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${badge.cls}`}>
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-slate-500">
                      {t.entry_price != null ? t.entry_price.toPrecision(5) : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500">
                      {t.exit_price != null ? t.exit_price.toPrecision(5) : "—"}
                    </td>
                    <td className={`px-2 py-1.5 font-semibold ${win ? "text-green-400" : pnl < 0 ? "text-red-400" : "text-slate-400"}`}>
                      {pnl !== 0 ? (win ? "+" : "") + "$" + pnl.toFixed(2) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className={`px-2 py-1.5 ${win ? "text-green-400" : pnl < 0 ? "text-red-400" : "text-slate-600"}`}>
                      {pnl !== 0 ? (win ? "+" : "") + pct.toFixed(1) + "%" : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500">{t.setup_type ?? "—"}</td>
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
