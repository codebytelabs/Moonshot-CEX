"use client";
import { useState } from "react";
import { Play, Square, AlertTriangle } from "lucide-react";

interface AgentInfo {
  name: string;
  status: string;
  runs?: number;
  errors?: number;
}

interface Props {
  swarmStatus: Record<string, unknown> | null;
  agents: Record<string, unknown> | null;
  onAction: (action: "start" | "stop" | "emergency") => Promise<void>;
}

const REGIME_COLORS: Record<string, string> = {
  bull:     "text-green-400 border-green-500/40 bg-green-500/8",
  sideways: "text-amber-400 border-amber-500/40 bg-amber-500/8",
  bear:     "text-red-400 border-red-500/40 bg-red-500/8",
  choppy:   "text-orange-400 border-orange-500/40 bg-orange-500/8",
};

const MODE_COLORS: Record<string, string> = {
  normal:   "text-cyan-400",
  volatile: "text-amber-400",
  safety:   "text-red-400",
  paused:   "text-slate-500",
};

const AGENT_ICONS: Record<string, string> = {
  watcher:          "👁",
  analyzer:         "🔬",
  context:          "🌐",
  bayesian:         "🎲",
  execution:        "⚡",
  position_manager: "📊",
  risk_manager:     "🛡",
  quant_mutator:    "🧬",
  bigbrother:       "🤖",
};

export default function SideSummary({ swarmStatus, agents, onAction }: Props) {
  const [loading, setLoading] = useState(false);

  const regime     = (swarmStatus?.regime as string) ?? "sideways";
  const mode       = (swarmStatus?.bigbrother_mode as string) ?? (swarmStatus?.mode as string) ?? "normal";
  const active     = Boolean(swarmStatus?.running);
  const cycleCount = Number(swarmStatus?.cycle_count ?? 0);
  const drawdown   = Number(swarmStatus?.drawdown ?? 0);
  const winRate    = Number(swarmStatus?.win_rate ?? 0);
  const consLosses = Number(swarmStatus?.consecutive_losses ?? 0);

  const agentList: AgentInfo[] = agents
    ? Object.entries(agents).map(([name, data]) => ({
        name,
        ...((data as Record<string, unknown>) ?? {}),
        status: (data as Record<string, unknown>)?.status as string ?? "unknown",
      }))
    : [];
  const healthyCount = agentList.filter((a) => a.status === "ok" || a.status === "idle").length;

  const handle = async (action: "start" | "stop" | "emergency") => {
    setLoading(true);
    try { await onAction(action); } finally { setLoading(false); }
  };

  return (
    <div className="h-full panel flex flex-col overflow-hidden text-[9px] mono">
      {/* ── Regime + Mode ───────────────────────────── */}
      <div className="px-2 pt-2 pb-1.5 border-b border-white/5 shrink-0 flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase tracking-wider ${REGIME_COLORS[regime] ?? REGIME_COLORS.sideways}`}>
          {regime === "bull" ? "🐂" : regime === "bear" ? "🐻" : regime === "choppy" ? "⚡" : "〰"} {regime}
        </span>
        <span className={`font-semibold uppercase ${MODE_COLORS[mode] ?? "text-slate-400"}`}>{mode}</span>
        <div className="ml-auto flex items-center gap-1">
          <div className={`w-1.5 h-1.5 rounded-full ${active ? "bg-green-400 animate-pulse" : "bg-slate-600"}`} />
          <span className={active ? "text-green-400" : "text-slate-500"}>{active ? "ON" : "OFF"}</span>
        </div>
      </div>

      {/* ── Key metrics ─────────────────────────────── */}
      <div className="px-2 py-1.5 border-b border-white/5 shrink-0 grid grid-cols-2 gap-x-2 gap-y-0.5">
        {[
          { label: "Cycles",    value: cycleCount,                       fmt: (v: number) => String(v),                          color: "text-slate-400" },
          { label: "Drawdown",  value: drawdown,                         fmt: (v: number) => `${(v * 100).toFixed(1)}%`,          color: drawdown > 0.05 ? "text-red-400" : "text-slate-400" },
          { label: "Win Rate",  value: winRate,                          fmt: (v: number) => `${(v * 100).toFixed(0)}%`,          color: winRate > 0.55 ? "text-green-400" : "text-slate-400" },
          { label: "Streak",    value: consLosses,                       fmt: (v: number) => v > 0 ? `-${v}L` : "OK",             color: consLosses >= 3 ? "text-red-400" : "text-slate-400" },
        ].map((s) => (
          <div key={s.label} className="flex justify-between">
            <span className="text-slate-600">{s.label}</span>
            <span className={`font-semibold ${s.color}`}>{s.fmt(s.value)}</span>
          </div>
        ))}
      </div>

      {/* ── Agents list ─────────────────────────────── */}
      <div className="px-2 pt-1 pb-0.5 border-b border-white/5 shrink-0 flex items-center justify-between">
        <span className="text-[8px] text-slate-600 uppercase tracking-wider">Agents</span>
        <span className="text-[8px] text-slate-600">{healthyCount}/{agentList.length} ✓</span>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-0.5 min-h-0">
        {agentList.map((agent) => {
          const ok  = agent.status === "ok" || agent.status === "idle";
          const err = agent.status === "error";
          return (
            <div key={agent.name} className="flex items-center gap-1.5 py-0.5">
              <span className="text-[10px]">{AGENT_ICONS[agent.name] ?? "⚙"}</span>
              <span className="flex-1 text-slate-400 capitalize truncate">{agent.name.replace(/_/g, " ")}</span>
              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ok ? "bg-green-400" : err ? "bg-red-400" : "bg-amber-400"}`} />
            </div>
          );
        })}
      </div>

      {/* ── Controls ────────────────────────────────── */}
      <div className="px-2 pb-2 pt-1 shrink-0 flex gap-1">
        {!active ? (
          <button
            onClick={() => handle("start")}
            disabled={loading}
            className="flex-1 flex items-center justify-center gap-1 py-1 bg-green-500/15 border border-green-500/30 rounded text-[9px] text-green-400 hover:bg-green-500/25 transition-colors disabled:opacity-50"
          >
            <Play size={8} /> GO
          </button>
        ) : (
          <button
            onClick={() => handle("stop")}
            disabled={loading}
            className="flex-1 flex items-center justify-center gap-1 py-1 bg-slate-500/10 border border-slate-500/20 rounded text-[9px] text-slate-400 hover:bg-slate-500/20 transition-colors disabled:opacity-50"
          >
            <Square size={8} /> STOP
          </button>
        )}
        <button
          onClick={() => handle("emergency")}
          disabled={loading}
          title="Emergency Stop"
          className="flex items-center justify-center px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
        >
          <AlertTriangle size={8} />
        </button>
      </div>
    </div>
  );
}
