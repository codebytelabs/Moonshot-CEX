"use client";

interface Candidate {
  symbol: string;
  score: number;
  rsi: number;
  pct_change_24h: number;
  vol_usd: number;
  setup_type?: string;
  ta_score?: number;
}

interface Props {
  feed: Record<string, unknown> | null;
}

export default function MarketFeed({ feed }: Props) {
  const candidates = (feed?.candidates as Candidate[]) ?? [];
  const setups = (feed?.setups as Candidate[]) ?? [];
  const events = (feed?.events as { type: string; detail: string; timestamp: number }[]) ?? [];

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Market Feed</span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-1 min-h-0">
        {setups.length > 0 && (
          <>
            <p className="text-[9px] mono text-slate-600 uppercase tracking-widest px-1 pt-1">Active Setups</p>
            {setups.slice(0, 5).map((s, i) => (
              <div key={i} className="panel-card px-2 py-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-cyan-300 mono">{s.symbol}</span>
                  <span className={`text-[10px] mono font-bold ${(s.ta_score ?? 0) >= 60 ? "text-green-400" : "text-amber-400"}`}>
                    {(s.ta_score ?? s.score ?? 0).toFixed(0)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[9px] text-slate-500 mono">{s.setup_type ?? "scan"}</span>
                  <span className={`text-[9px] mono ${(s.pct_change_24h ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {(s.pct_change_24h ?? 0) >= 0 ? "+" : ""}{(s.pct_change_24h ?? 0).toFixed(1)}%
                  </span>
                  <span className="text-[9px] text-slate-600 mono">RSI {(s.rsi ?? 0).toFixed(0)}</span>
                </div>
              </div>
            ))}
          </>
        )}

        {candidates.length > 0 && (
          <>
            <p className="text-[9px] mono text-slate-600 uppercase tracking-widest px-1 pt-1">Watcher Scan</p>
            {candidates.slice(0, 8).map((c, i) => (
              <div key={i} className="flex items-center justify-between px-2 py-1 hover:bg-white/3 rounded-md">
                <span className="text-[10px] mono text-slate-300">{c.symbol}</span>
                <div className="flex items-center gap-2">
                  <span className={`text-[9px] mono ${c.pct_change_24h >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {c.pct_change_24h >= 0 ? "+" : ""}{c.pct_change_24h.toFixed(1)}%
                  </span>
                  <span className="text-[9px] mono text-slate-600">{c.score.toFixed(0)}</span>
                </div>
              </div>
            ))}
          </>
        )}

        {events.length > 0 && (
          <>
            <p className="text-[9px] mono text-slate-600 uppercase tracking-widest px-1 pt-1">Events</p>
            {events.slice(-6).reverse().map((e, i) => (
              <div key={i} className="flex items-start gap-1.5 px-2 py-0.5">
                <div className="w-1 h-1 rounded-full bg-amber-400 mt-1.5 shrink-0" />
                <div>
                  <span className="text-[9px] mono text-amber-400 uppercase">{e.type.replace(/_/g, " ")}</span>
                  <p className="text-[9px] text-slate-500 mono">{e.detail}</p>
                </div>
              </div>
            ))}
          </>
        )}

        {candidates.length === 0 && setups.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 text-slate-700">
            <span className="text-2xl">📡</span>
            <span className="text-[10px] mono mt-1">Awaiting scan...</span>
          </div>
        )}
      </div>
    </div>
  );
}
