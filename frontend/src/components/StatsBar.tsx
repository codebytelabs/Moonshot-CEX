"use client";

interface Props {
  swarmStatus: Record<string, unknown> | null;
  portfolio: Record<string, unknown> | null;
}

export default function StatsBar({ swarmStatus, portfolio }: Props) {
  const equity = Number(portfolio?.equity ?? swarmStatus?.equity ?? 0);
  const totalPnl = Number(portfolio?.total_pnl_usd ?? swarmStatus?.total_pnl_usd ?? 0);
  const dayPnl = Number(portfolio?.day_pnl_usd ?? swarmStatus?.day_pnl_usd ?? 0);
  const openCount = Number(portfolio?.open_count ?? swarmStatus?.open_count ?? 0);
  const drawdown = Number((swarmStatus?.drawdown as number) ?? 0);
  const winRate = Number((swarmStatus?.win_rate as number) ?? 0);
  const cycles = Number(swarmStatus?.cycle_count ?? 0);

  const stats = [
    { label: "EQUITY", value: `$${equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: "text-cyan-400", primary: true },
    { label: "TOTAL PnL", value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? "text-green-400" : "text-red-400", primary: true },
    { label: "TODAY", value: `${dayPnl >= 0 ? "+" : ""}$${dayPnl.toFixed(2)}`, color: dayPnl >= 0 ? "text-green-400" : "text-red-400", primary: true },
    { label: "POSITIONS", value: `${openCount}`, color: "text-slate-300", primary: true },
    { label: "DRAWDOWN", value: `${(drawdown * 100).toFixed(1)}%`, color: drawdown > 0.05 ? "text-red-400" : "text-slate-400", primary: false },
    { label: "WIN RATE", value: `${(winRate * 100).toFixed(0)}%`, color: winRate > 0.55 ? "text-green-400" : "text-slate-400", primary: false },
    { label: "CYCLES", value: cycles.toLocaleString(), color: "text-slate-500", primary: false },
  ];

  return (
    <>
      {/* Mobile: compact 2-row grid showing key stats */}
      <div className="grid grid-cols-4 gap-1 md:hidden">
        {stats.filter((s) => s.primary).map((s) => (
          <div
            key={s.label}
            className="flex flex-col items-center px-1.5 py-1.5 bg-[#0d1410] border border-white/5 rounded-md"
          >
            <span className="text-[8px] mono text-slate-600 uppercase tracking-wider">{s.label}</span>
            <span className={`text-[11px] font-bold mono ${s.color}`}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Desktop: horizontal flex */}
      <div className="hidden md:flex items-center gap-1 flex-wrap">
        {stats.map((s) => (
          <div
            key={s.label}
            className="flex items-center gap-1.5 px-2.5 py-1 bg-[#0d1410] border border-white/5 rounded-md"
          >
            <span className="text-[9px] mono text-slate-600 uppercase tracking-wider">{s.label}</span>
            <span className={`text-[11px] font-bold mono ${s.color}`}>{s.value}</span>
          </div>
        ))}
      </div>
    </>
  );
}
