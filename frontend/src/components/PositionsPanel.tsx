"use client";
import { apiFetch } from "@/lib/api";

interface Position {
  id: string;
  symbol: string;
  setup_type: string;
  entry_price: number;
  current_price: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  amount_usd: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  trailing_stop?: number;
  hold_time_hours: number;
  tier1_done: boolean;
  tier2_done: boolean;
  posterior: number;
}

interface Props {
  positions: unknown[];
  onClose?: () => void;
  readOnly?: boolean;
}

const COLS = ["Symbol", "Setup", "Entry", "Current", "Unr. PnL", "Size", "SL", "TP1", "TP2", "Trail", "Hold", "T1", "P(win)", ""];

export default function PositionsPanel({ positions, onClose, readOnly }: Props) {
  const pos = positions as Position[];

  const closePosition = async (id: string) => {
    try {
      await apiFetch(`/api/positions/${id}/close`, { method: "POST" });
      onClose?.();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0 flex items-center justify-between">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Open Positions</span>
        <span className="text-[10px] mono text-slate-600">{pos.length} active</span>
      </div>

      <div className="flex-1 overflow-auto min-h-0">
        {pos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-700">
            <span className="text-2xl">📊</span>
            <span className="text-[10px] mono mt-1">No open positions</span>
          </div>
        ) : (
          <>
            {/* ═══ MOBILE: Card layout ═══ */}
            <div className="md:hidden space-y-1.5 p-2">
              {pos.map((p) => {
                const urPnl = p.unrealized_pnl_usd ?? 0;
                const urPct = p.unrealized_pnl_pct ?? 0;
                const win = urPnl >= 0;
                return (
                  <div key={p.id} className="panel-card p-2.5">
                    {/* Row 1: Symbol + PnL + Close */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-bold text-cyan-300 mono">{p.symbol?.replace("/USDT", "")}</span>
                        <span className="text-[9px] text-slate-500 mono">{p.setup_type}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-[12px] font-bold mono ${win ? "text-green-400" : "text-red-400"}`}>
                          {win ? "+" : ""}{urPnl.toFixed(2)}
                          <span className="text-[9px] ml-0.5 opacity-70">({win ? "+" : ""}{urPct.toFixed(1)}%)</span>
                        </span>
                        {!readOnly && (
                          <button
                            onClick={() => closePosition(p.id)}
                            className="px-2 py-1 text-[9px] border border-red-500/30 text-red-400 rounded active:bg-red-500/20 transition-colors"
                          >
                            CLOSE
                          </button>
                        )}
                      </div>
                    </div>
                    {/* Row 2: Key details grid */}
                    <div className="grid grid-cols-4 gap-x-3 gap-y-0.5 mt-1.5 text-[9px] mono">
                      <div>
                        <span className="text-slate-600">Entry </span>
                        <span className="text-slate-300">{p.entry_price?.toPrecision(5)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600">Now </span>
                        <span className="text-slate-300">{p.current_price?.toPrecision(5)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600">Size </span>
                        <span className="text-slate-300">${p.amount_usd?.toFixed(0)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600">Hold </span>
                        <span className="text-slate-400">{p.hold_time_hours?.toFixed(1)}h</span>
                      </div>
                      <div>
                        <span className="text-slate-600">SL </span>
                        <span className="text-red-400">{p.stop_loss?.toPrecision(5)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600">TP1 </span>
                        <span className="text-green-400">{p.take_profit_1?.toPrecision(5)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600">Trail </span>
                        <span className="text-amber-400">{p.trailing_stop ? p.trailing_stop.toPrecision(5) : "—"}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <div className={`w-1.5 h-1.5 rounded-full ${p.tier1_done ? "bg-green-400" : "bg-slate-600"}`} />
                        <div className={`w-1.5 h-1.5 rounded-full ${p.tier2_done ? "bg-green-300" : "bg-slate-700"}`} />
                        <span className="text-slate-500 ml-0.5">{p.posterior != null ? `${(p.posterior * 100).toFixed(0)}%` : ""}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ═══ DESKTOP: Table layout ═══ */}
            <table className="hidden md:table w-full text-[10px] mono">
              <thead>
                <tr className="border-b border-white/5">
                  {COLS.map((h) => (
                    <th key={h} className="text-left px-1.5 py-1.5 text-slate-600 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pos.map((p) => {
                  const urPnl = p.unrealized_pnl_usd ?? 0;
                  const urPct = p.unrealized_pnl_pct ?? 0;
                  const win   = urPnl >= 0;
                  return (
                    <tr key={p.id} className="border-b border-white/3 hover:bg-white/2">
                      <td className="px-1.5 py-1.5 text-cyan-300 font-semibold whitespace-nowrap">
                        {p.symbol?.replace("/USDT", "")}
                      </td>
                      <td className="px-1.5 py-1.5 text-slate-400 whitespace-nowrap">{p.setup_type}</td>
                      <td className="px-1.5 py-1.5 text-slate-300 whitespace-nowrap">{p.entry_price?.toPrecision(5)}</td>
                      <td className="px-1.5 py-1.5 text-slate-300 whitespace-nowrap">{p.current_price?.toPrecision(5)}</td>
                      <td className={`px-1.5 py-1.5 font-semibold whitespace-nowrap ${win ? "text-green-400" : "text-red-400"}`}>
                        {win ? "+" : ""}{urPnl.toFixed(2)}
                        <span className="text-[8px] ml-0.5 opacity-70">({win ? "+" : ""}{urPct.toFixed(1)}%)</span>
                      </td>
                      <td className="px-1.5 py-1.5 text-slate-300 whitespace-nowrap">${p.amount_usd?.toFixed(0)}</td>
                      <td className="px-1.5 py-1.5 text-red-400 whitespace-nowrap">{p.stop_loss?.toPrecision(5)}</td>
                      <td className="px-1.5 py-1.5 text-green-400 whitespace-nowrap">{p.take_profit_1?.toPrecision(5)}</td>
                      <td className="px-1.5 py-1.5 text-green-300 whitespace-nowrap">{p.take_profit_2?.toPrecision(5) ?? "—"}</td>
                      <td className="px-1.5 py-1.5 text-amber-400 whitespace-nowrap">
                        {p.trailing_stop ? p.trailing_stop.toPrecision(5) : "—"}
                      </td>
                      <td className="px-1.5 py-1.5 text-slate-500 whitespace-nowrap">{p.hold_time_hours?.toFixed(1)}h</td>
                      <td className="px-1.5 py-1.5 whitespace-nowrap">
                        <div className="flex gap-0.5">
                          <div className={`w-1.5 h-1.5 rounded-full ${p.tier1_done ? "bg-green-400" : "bg-slate-600"}`} title="TP1" />
                          <div className={`w-1.5 h-1.5 rounded-full ${p.tier2_done ? "bg-green-300" : "bg-slate-700"}`} title="TP2" />
                        </div>
                      </td>
                      <td className="px-1.5 py-1.5 text-slate-400 whitespace-nowrap">
                        {p.posterior != null ? `${(p.posterior * 100).toFixed(0)}%` : "—"}
                      </td>
                      {!readOnly && (
                        <td className="px-1.5 py-1.5 whitespace-nowrap">
                          <button
                            onClick={() => closePosition(p.id)}
                            className="px-1.5 py-0.5 text-[8px] border border-red-500/30 text-red-400 rounded hover:bg-red-500/10 transition-colors"
                          >
                            CLOSE
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
