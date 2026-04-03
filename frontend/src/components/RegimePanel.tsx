"use client";

interface Props {
  swarmStatus: Record<string, unknown> | null;
}

const REGIME_COLORS: Record<string, string> = {
  bull: "text-green-400 border-green-500/30 bg-green-500/5",
  sideways: "text-amber-400 border-amber-500/30 bg-amber-500/5",
  bear: "text-red-400 border-red-500/30 bg-red-500/5",
};

const MODE_COLORS: Record<string, string> = {
  normal: "text-cyan-400",
  volatile: "text-amber-400",
  safety: "text-red-400",
  paused: "text-slate-500",
};

export default function RegimePanel({ swarmStatus }: Props) {
  const regime = (swarmStatus?.regime as string) ?? "sideways";
  const mode = (swarmStatus?.bigbrother_mode as string) ?? (swarmStatus?.mode as string) ?? "normal";
  const drawdown = Number(swarmStatus?.drawdown ?? 0);
  const winRate = Number(swarmStatus?.win_rate ?? 0);
  const consLosses = Number(swarmStatus?.consecutive_losses ?? 0);
  const params = (swarmStatus?.regime_params as Record<string, number>) ?? {};

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Regime</span>
      </div>

      <div className="flex-1 px-3 py-2 space-y-2 overflow-y-auto min-h-0">
        <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded border text-xs font-bold mono uppercase tracking-wider ${REGIME_COLORS[regime] ?? REGIME_COLORS.sideways}`}>
          <span>{regime === "bull" ? "🐂" : regime === "bear" ? "🐻" : "〰"}</span>
          {regime}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[9px] mono text-slate-600 uppercase">Mode</span>
          <span className={`text-[10px] mono font-semibold ${MODE_COLORS[mode] ?? "text-slate-400"}`}>
            {mode.toUpperCase()}
          </span>
        </div>

        <div className="space-y-1">
          {[
            { label: "Drawdown", value: `${(drawdown * 100).toFixed(1)}%`, color: drawdown > 0.05 ? "text-red-400" : "text-slate-400" },
            { label: "Win Rate", value: `${(winRate * 100).toFixed(0)}%`, color: winRate > 0.55 ? "text-green-400" : "text-slate-400" },
            { label: "Streak", value: `${consLosses > 0 ? `-${consLosses}L` : "OK"}`, color: consLosses >= 3 ? "text-red-400" : "text-slate-400" },
          ].map((s) => (
            <div key={s.label} className="flex items-center justify-between">
              <span className="text-[9px] mono text-slate-600">{s.label}</span>
              <span className={`text-[10px] mono font-semibold ${s.color}`}>{s.value}</span>
            </div>
          ))}
        </div>

        {Object.keys(params).length > 0 && (
          <div className="border-t border-white/5 pt-2 space-y-0.5">
            <p className="text-[9px] mono text-slate-600 uppercase mb-1">Regime Params</p>
            {["stop_loss_pct", "trailing_activate_pct", "trailing_distance_pct", "time_exit_hours"].map((k) =>
              params[k] !== undefined ? (
                <div key={k} className="flex justify-between">
                  <span className="text-[8px] mono text-slate-700">{k.replace(/_/g, " ").replace("pct", "%").replace("hours", "h")}</span>
                  <span className="text-[9px] mono text-slate-500">{params[k]}</span>
                </div>
              ) : null
            )}
          </div>
        )}
      </div>
    </div>
  );
}
