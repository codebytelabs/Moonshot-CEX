"use client";
import { useEffect, useState, useCallback } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { apiFetch } from "@/lib/api";
import { TrendingUp, TrendingDown } from "lucide-react";

interface EquityPoint {
  t: number;
  v: number;
}

interface NavChartProps {
  currentEquity?: number;
}

const INTERVALS = [
  { label: "Session", since: 0 },
  { label: "1H", since: 3600 },
  { label: "6H", since: 6 * 3600 },
  { label: "1D", since: 86400 },
  { label: "7D", since: 7 * 86400 },
  { label: "30D", since: 30 * 86400 },
] as const;

export default function NavChart({ currentEquity }: NavChartProps) {
  const [history, setHistory] = useState<EquityPoint[]>([]);
  const [peak, setPeak] = useState<number>(0);
  const [startEquity, setStartEquity] = useState<number>(0);
  const [interval, setInterval_] = useState<number>(0); // 0 = session (in-memory)

  const load = useCallback(async () => {
    try {
      const since = interval > 0 ? Math.floor(Date.now() / 1000) - interval : 0;
      const url = since > 0 ? `/api/equity/history?since=${since}` : "/api/equity/history";
      const data = await apiFetch(url);
      const hist: EquityPoint[] = data.history || [];
      setHistory(hist);
      setPeak(data.peak || 0);
      if (hist.length > 0 && startEquity === 0) {
        setStartEquity(hist[0].v);
      }
    } catch {
      // silent
    }
  }, [interval, startEquity]);

  // Reset start equity when interval changes
  const handleIntervalChange = (since: number) => {
    setStartEquity(0);
    setInterval_(since);
  };

  useEffect(() => {
    load();
    const t = window.setInterval(load, 15000);
    return () => window.clearInterval(t);
  }, [load]);

  const equity = currentEquity ?? (history.length ? history[history.length - 1]?.v : 0);
  const base = startEquity || equity;
  const pnlUsd = equity - base;
  const pnlPct = base > 0 ? (pnlUsd / base) * 100 : 0;
  const isUp = pnlUsd >= 0;
  const drawdown = peak > 0 ? ((peak - equity) / peak) * 100 : 0;

  const fmt = (t: number, since: number) => {
    const d = new Date(t * 1000);
    if (since >= 7 * 86400) {
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    }
    if (since >= 86400) {
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + " " +
        d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  };

  const chartData = history.map((p) => ({
    t: p.t,
    v: p.v,
    label: fmt(p.t, interval),
  }));

  const minV = chartData.length ? Math.min(...chartData.map((d) => d.v)) * 0.9995 : 0;
  const maxV = chartData.length ? Math.max(...chartData.map((d) => d.v)) * 1.0005 : 1;

  return (
    <div className="h-full flex flex-col bg-[#090E0C] border border-cyan-900/20 rounded p-2 gap-1">
      <div className="flex items-center justify-between shrink-0">
        <span className="text-[10px] mono text-cyan-500 tracking-widest">NAV CHART</span>
        <div className={`flex items-center gap-1 text-[10px] mono font-bold ${isUp ? "text-green-400" : "text-red-400"}`}>
          {isUp ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          <span>{pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%</span>
          <span className="text-slate-600 font-normal">({pnlUsd >= 0 ? "+" : ""}${pnlUsd.toFixed(2)})</span>
        </div>
      </div>

      {/* Interval selector */}
      <div className="flex gap-1 shrink-0">
        {INTERVALS.map(({ label, since }) => (
          <button
            key={label}
            onClick={() => handleIntervalChange(since)}
            className={`px-1.5 py-0.5 text-[9px] mono rounded transition-colors ${
              interval === since
                ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/40"
                : "text-slate-600 hover:text-slate-400 border border-transparent"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex gap-3 shrink-0 px-0.5">
        <div>
          <div className="text-[9px] mono text-slate-600">EQUITY</div>
          <div className="text-xs mono text-white font-bold">${equity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div>
          <div className="text-[9px] mono text-slate-600">PEAK</div>
          <div className="text-xs mono text-cyan-400">${peak.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div>
          <div className="text-[9px] mono text-slate-600">DRAWDOWN</div>
          <div className={`text-xs mono ${drawdown > 5 ? "text-red-400" : drawdown > 2 ? "text-yellow-400" : "text-green-400"}`}>
            -{drawdown.toFixed(2)}%
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {chartData.length < 2 ? (
          <div className="h-full flex items-center justify-center text-[10px] mono text-slate-700">
            {interval > 0 ? "No historical data for this range yet — collecting…" : "Collecting equity data…"}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 2, right: 2, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="navGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={isUp ? "#22d3ee" : "#f87171"} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={isUp ? "#22d3ee" : "#f87171"} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                tick={{ fontSize: 8, fill: "#475569", fontFamily: "monospace" }}
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={[minV, maxV]}
                tick={{ fontSize: 8, fill: "#475569", fontFamily: "monospace" }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                width={48}
              />
              <Tooltip
                contentStyle={{ background: "#0A0F0D", border: "1px solid rgba(34,211,238,0.2)", borderRadius: 4, fontSize: 10, fontFamily: "monospace" }}
                labelStyle={{ color: "#64748b" }}
                formatter={(value: number) => [`$${value.toLocaleString("en-US", { minimumFractionDigits: 2 })}`, "Equity"]}
              />
              {base > 0 && <ReferenceLine y={base} stroke="#334155" strokeDasharray="3 3" />}
              <Area
                type="monotone"
                dataKey="v"
                stroke={isUp ? "#22d3ee" : "#f87171"}
                strokeWidth={1.5}
                fill="url(#navGrad)"
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
