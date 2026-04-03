"use client";
import { useState } from "react";
import { Play, Square, AlertTriangle } from "lucide-react";

interface Props {
  swarmStatus: Record<string, unknown> | null;
  onAction: (action: "start" | "stop" | "emergency") => Promise<void>;
}

export default function SwarmControl({ swarmStatus, onAction }: Props) {
  const [loading, setLoading] = useState(false);
  const active = Boolean(swarmStatus?.running);
  const mode = (swarmStatus?.mode as string) ?? "paper";
  const exchange = "GATEIO";
  const cycleCount = Number(swarmStatus?.cycle_count ?? 0);

  const handle = async (action: "start" | "stop" | "emergency") => {
    setLoading(true);
    try { await onAction(action); } finally { setLoading(false); }
  };

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-2 pt-2 pb-1 border-b border-white/5 shrink-0 flex items-center gap-1.5">
        <div className={`w-1.5 h-1.5 rounded-full ${active ? "bg-green-400 animate-pulse" : "bg-slate-600"}`} />
        <span className={`text-[9px] font-semibold mono ${active ? "text-green-400" : "text-slate-500"}`}>
          {active ? "RUNNING" : "STOPPED"}
        </span>
      </div>

      <div className="flex-1 px-2 py-1.5 flex flex-col gap-1 justify-between">
        <div className="space-y-0.5">
          <div className="flex justify-between">
            <span className="text-[8px] mono text-slate-600">Cycles</span>
            <span className="text-[8px] mono text-slate-400">{cycleCount}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[8px] mono text-slate-600">Mode</span>
            <span className="text-[8px] mono text-slate-400">{mode.toUpperCase()}</span>
          </div>
        </div>

        <div className="space-y-1">
          {!active ? (
            <button
              onClick={() => handle("start")}
              disabled={loading}
              className="w-full flex items-center justify-center gap-1 py-1 bg-green-500/15 border border-green-500/30 rounded text-[9px] mono text-green-400 hover:bg-green-500/25 transition-colors disabled:opacity-50"
            >
              <Play size={9} />
              GO
            </button>
          ) : (
            <button
              onClick={() => handle("stop")}
              disabled={loading}
              className="w-full flex items-center justify-center gap-1 py-1 bg-slate-500/10 border border-slate-500/20 rounded text-[9px] mono text-slate-400 hover:bg-slate-500/20 transition-colors disabled:opacity-50"
            >
              <Square size={9} />
              STOP
            </button>
          )}
          <button
            onClick={() => handle("emergency")}
            disabled={loading}
            title="Emergency Stop"
            className="w-full flex items-center justify-center py-1 bg-red-500/10 border border-red-500/30 rounded text-[8px] mono text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
          >
            <AlertTriangle size={9} />
          </button>
        </div>
      </div>
    </div>
  );
}
