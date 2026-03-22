"use client";

interface Position {
  id: string;
  symbol: string;
  entry_price: number;
  amount_usd: number;
  stop_loss: number;
  take_profit_1: number;
  setup_type: string;
  opened_at: number;
  hold_time_hours: number;
  tier1_done: boolean;
  posterior: number;
}

interface Props {
  positions: unknown[];
}

export default function PositionsPanel({ positions }: Props) {
  const pos = positions as Position[];

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0 flex items-center justify-between">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Open Positions</span>
        <span className="text-[10px] mono text-slate-600">{pos.length} active</span>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {pos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-700">
            <span className="text-2xl">📊</span>
            <span className="text-[10px] mono mt-1">No open positions</span>
          </div>
        ) : (
          <table className="w-full text-[10px] mono">
            <thead>
              <tr className="border-b border-white/5">
                {["Symbol", "Setup", "Entry", "Size", "SL", "TP1", "Hold", "P"].map((h) => (
                  <th key={h} className="text-left px-2 py-1.5 text-slate-600 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pos.map((p) => (
                <tr key={p.id} className="border-b border-white/3 hover:bg-white/2">
                  <td className="px-2 py-1.5 text-cyan-300 font-semibold">{p.symbol}</td>
                  <td className="px-2 py-1.5 text-slate-400">{p.setup_type}</td>
                  <td className="px-2 py-1.5 text-slate-300">{p.entry_price?.toFixed(5)}</td>
                  <td className="px-2 py-1.5 text-slate-300">${p.amount_usd?.toFixed(0)}</td>
                  <td className="px-2 py-1.5 text-red-400">{p.stop_loss?.toFixed(5)}</td>
                  <td className="px-2 py-1.5 text-green-400">{p.take_profit_1?.toFixed(5)}</td>
                  <td className="px-2 py-1.5 text-slate-500">{p.hold_time_hours?.toFixed(1)}h</td>
                  <td className="px-2 py-1.5">
                    <div className={`w-1.5 h-1.5 rounded-full ${p.tier1_done ? "bg-green-400" : "bg-amber-400"}`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
