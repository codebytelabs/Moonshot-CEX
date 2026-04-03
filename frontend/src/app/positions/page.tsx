"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { apiFetch } from "@/lib/api";
import { Download, RefreshCw } from "lucide-react";

interface Position {
  id: string;
  symbol: string;
  entry_price: number;
  current_price: number;
  amount_usd: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  setup_type: string;
  opened_at: number;
  hold_time_hours: number;
  tier1_done: boolean;
  posterior: number;
  trailing_stop?: number;
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<unknown[]>([]);

  const load = async () => {
    try {
      const data = await apiFetch("/api/portfolio");
      setPositions((data.open_positions as Position[]) ?? []);
      const h = await apiFetch("/api/trades?limit=100");
      setHistory(h.trades ?? []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const syncHoldings = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await apiFetch("/api/positions/sync-holdings", { method: "POST" });
      setSyncMsg(`Synced ${res.total_synced} holding(s). Total open: ${res.total_open}`);
      await load();
    } catch (e) {
      setSyncMsg("Sync failed");
      console.error(e);
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(null), 5000);
    }
  };

  const closePosition = async (id: string) => {
    try {
      await apiFetch(`/api/positions/${id}/close`, { method: "POST" });
      await load();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 flex items-center px-4 gap-3">
          <span className="text-xs font-bold tracking-[0.25em] uppercase neon-text-cyan mono">Positions</span>
          <span className="text-[10px] mono text-slate-600">{positions.length} open</span>
          <div className="ml-auto flex items-center gap-2">
            {syncMsg && (
              <span className="text-[9px] mono text-cyan-400 animate-pulse">{syncMsg}</span>
            )}
            <button
              onClick={syncHoldings}
              disabled={syncing}
              title="Import existing exchange holdings as tracked positions"
              className="flex items-center gap-1.5 px-2.5 py-1 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/20 rounded text-[10px] mono text-cyan-400 transition-colors disabled:opacity-50"
            >
              {syncing ? <RefreshCw size={10} className="animate-spin" /> : <Download size={10} />}
              Sync Holdings
            </button>
          </div>
        </header>

        <div className="p-4 space-y-4">
          <section>
            <h2 className="text-[10px] mono text-slate-600 uppercase tracking-widest mb-2">Open Positions</h2>
            {positions.length === 0 ? (
              <div className="panel p-8 flex flex-col items-center text-slate-700">
                <span className="text-3xl">📊</span>
                <span className="text-[11px] mono mt-2">No open positions</span>
              </div>
            ) : (
              <div className="panel overflow-hidden">
                <table className="w-full text-[10px] mono">
                  <thead>
                    <tr className="border-b border-white/5">
                      {["Symbol", "Setup", "Entry", "Current", "Unr. PnL", "Size USD", "SL", "TP1", "TP2", "Trail", "Hold", "Tier1", "P(win)", "Action"].map((h) => (
                        <th key={h} className="text-left px-3 py-2 text-slate-600 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => {
                      const urPnl = p.unrealized_pnl_usd ?? 0;
                      const urPct = p.unrealized_pnl_pct ?? 0;
                      const urWin = urPnl >= 0;
                      return (
                        <tr key={p.id} className="border-b border-white/3 hover:bg-white/2">
                          <td className="px-3 py-2 text-cyan-300 font-semibold">{p.symbol}</td>
                          <td className="px-3 py-2 text-slate-400">{p.setup_type}</td>
                          <td className="px-3 py-2 text-slate-300">{p.entry_price?.toPrecision(6)}</td>
                          <td className="px-3 py-2 text-slate-300">{p.current_price?.toPrecision(6)}</td>
                          <td className={`px-3 py-2 font-semibold ${urWin ? "text-green-400" : "text-red-400"}`}>
                            {urWin ? "+" : ""}{urPnl.toFixed(2)} ({urWin ? "+" : ""}{urPct.toFixed(1)}%)
                          </td>
                          <td className="px-3 py-2 text-slate-300">${p.amount_usd?.toFixed(2)}</td>
                          <td className="px-3 py-2 text-red-400">{p.stop_loss?.toPrecision(6)}</td>
                          <td className="px-3 py-2 text-green-400">{p.take_profit_1?.toPrecision(6)}</td>
                          <td className="px-3 py-2 text-green-300">{p.take_profit_2?.toPrecision(6)}</td>
                          <td className="px-3 py-2 text-amber-400">{p.trailing_stop ? p.trailing_stop.toPrecision(6) : "—"}</td>
                          <td className="px-3 py-2 text-slate-500">{p.hold_time_hours?.toFixed(1)}h</td>
                          <td className="px-3 py-2">
                            <div className={`w-2 h-2 rounded-full ${p.tier1_done ? "bg-green-400" : "bg-slate-600"}`} />
                          </td>
                          <td className="px-3 py-2 text-slate-400">{(p.posterior * 100).toFixed(0)}%</td>
                          <td className="px-3 py-2">
                            <button
                              onClick={() => closePosition(p.id)}
                              className="px-2 py-0.5 text-[9px] border border-red-500/30 text-red-400 rounded hover:bg-red-500/10"
                            >
                              CLOSE
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h2 className="text-[10px] mono text-slate-600 uppercase tracking-widest mb-2">
              Trade History ({(history as unknown[]).length})
            </h2>
            <div className="panel overflow-hidden">
              <table className="w-full text-[10px] mono">
                <thead>
                  <tr className="border-b border-white/5">
                    {["Symbol", "Reason", "Entry", "Exit", "PnL USD", "PnL %", "Hold", "Setup"].map((h) => (
                      <th key={h} className="text-left px-3 py-2 text-slate-600 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(history as Record<string, unknown>[]).slice().reverse().map((t, i) => {
                    const pnl = Number(t.pnl_usd ?? 0);
                    const win = pnl >= 0;
                    return (
                      <tr key={i} className="border-b border-white/3 hover:bg-white/2">
                        <td className="px-3 py-1.5">
                          <div className="flex items-center gap-1">
                            <div className={`w-1.5 h-1.5 rounded-full ${win ? "bg-green-400" : "bg-red-400"}`} />
                            <span className="text-slate-300">{t.symbol as string}</span>
                          </div>
                        </td>
                        <td className="px-3 py-1.5 text-slate-500">{((t.close_reason as string) ?? "").replace(/_/g, " ")}</td>
                        <td className="px-3 py-1.5 text-slate-400">{Number(t.entry_price ?? 0).toPrecision(5)}</td>
                        <td className="px-3 py-1.5 text-slate-400">{Number(t.exit_price ?? 0).toPrecision(5)}</td>
                        <td className={`px-3 py-1.5 font-semibold ${win ? "text-green-400" : "text-red-400"}`}>
                          {win ? "+" : ""}${pnl.toFixed(2)}
                        </td>
                        <td className={`px-3 py-1.5 ${win ? "text-green-400" : "text-red-400"}`}>
                          {win ? "+" : ""}{Number(t.pnl_pct ?? 0).toFixed(1)}%
                        </td>
                        <td className="px-3 py-1.5 text-slate-600">{Number(t.hold_time_hours ?? 0).toFixed(1)}h</td>
                        <td className="px-3 py-1.5 text-slate-500">{t.setup_type as string ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
