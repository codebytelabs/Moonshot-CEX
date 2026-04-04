"use client";
import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { useSwarmSocket } from "@/lib/useWebSocket";
import { useReadOnly } from "@/lib/useReadOnly";
import Sidebar from "@/components/Sidebar";
import MobileNav from "@/components/MobileNav";
import StatsBar from "@/components/StatsBar";
import MarketFeed from "@/components/MarketFeed";
import PositionsPanel from "@/components/PositionsPanel";
import TradeLog from "@/components/TradeLog";
import SideSummary from "@/components/SideSummary";
import NavChart from "@/components/NavChart";
import IssueBanner from "@/components/IssueBanner";

export default function Dashboard() {
  const [swarmStatus, setSwarmStatus] = useState<Record<string, unknown> | null>(null);
  const [portfolio, setPortfolio] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState<Record<string, unknown> | null>(null);
  const [feed, setFeed] = useState<Record<string, unknown> | null>(null);
  const [trades, setTrades] = useState<unknown[]>([]);
  const [mounted, setMounted] = useState(false);
  const [currentTime, setCurrentTime] = useState("");
  const { messages, connected } = useSwarmSocket();
  const readOnly = useReadOnly();

  const load = async () => {
    try {
      const [status, port, agts, fd, trds] = await Promise.all([
        apiFetch("/api/swarm/status"),
        apiFetch("/api/portfolio"),
        apiFetch("/api/agents"),
        apiFetch("/api/feed"),
        apiFetch("/api/trades?limit=30"),
      ]);
      setSwarmStatus(status);
      setPortfolio(port);
      setAgents(agts);
      setFeed(fd);
      setTrades(trds.trades || []);
    } catch (e) {
      console.error("Load error:", e);
    }
  };

  useEffect(() => {
    setMounted(true);
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (messages.length === 0) return;
    const latest = messages[messages.length - 1];
    if (latest?.type === "cycle_update") {
      const data = latest as Record<string, unknown>;
      setSwarmStatus((prev) => ({ ...(prev ?? {}), ...data }));
      if (data.open_positions) {
        setPortfolio((prev) => ({
          ...(prev ?? {}),
          open_positions: data.open_positions,
          open_count: data.open_count,
          equity: data.equity,
          total_pnl_usd: data.total_pnl_usd,
          day_pnl_usd: data.day_pnl_usd,
        }));
      }
      if (Array.isArray(data.recent_trades) && data.recent_trades.length > 0) {
        setTrades((prev) => {
          const incoming = data.recent_trades as Record<string, unknown>[];
          const existingIds = new Set(
            (prev as Record<string, unknown>[]).map((t) => t.id).filter(Boolean)
          );
          const newOnes = incoming.filter((t) => t.id && !existingIds.has(t.id));
          return newOnes.length > 0 ? [...prev, ...newOnes] : prev;
        });
      }
    }
  }, [messages]);

  useEffect(() => {
    const tick = () =>
      setCurrentTime(new Date().toLocaleTimeString("en-US", { hour12: false }));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  const handleSwarmToggle = async (action: "start" | "stop" | "emergency") => {
    try {
      await apiFetch(`/api/swarm/${action === "emergency" ? "emergency-stop" : action}`, { method: "POST" });
      await load();
    } catch (e) {
      console.error("Swarm control error:", e);
    }
  };

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />

      <main className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        {/* Header — compact on mobile */}
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 backdrop-blur flex items-center px-3 md:px-4 gap-2 md:gap-3">
          <span className="text-[10px] md:text-xs font-bold tracking-[0.2em] md:tracking-[0.25em] uppercase neon-text-cyan mono">
            M-CEX
          </span>
          <span className="hidden sm:inline text-[10px] mono text-slate-600">
            {swarmStatus?.exchange_mode === "paper"
              ? "// PAPER"
              : swarmStatus?.exchange_mode === "demo"
              ? "// DEMO"
              : "// LIVE"}
          </span>
          <div className="ml-auto flex items-center gap-2 md:gap-4">
            <span className="hidden sm:inline text-[10px] mono text-slate-500">
              {(swarmStatus?.exchange as string || "").toUpperCase()}
            </span>
            <div
              className={`flex items-center gap-1.5 text-[10px] mono ${
                connected ? "text-green-400" : "text-red-400"
              }`}
            >
              <div
                className={`w-1.5 h-1.5 rounded-full ${
                  connected ? "bg-green-400 animate-pulse" : "bg-red-400"
                }`}
              />
              <span className="hidden sm:inline">{connected ? "LIVE" : "OFF"}</span>
            </div>
            {readOnly && (
              <span className="px-1.5 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 text-[8px] font-bold text-amber-400 mono tracking-wider">
                LIVE VIEW
              </span>
            )}
            <span className="text-[10px] mono text-slate-600">
              {mounted ? currentTime : "--:--:--"}
            </span>
          </div>
        </header>

        {/* Issue banner — self-improvement alerts */}
        <IssueBanner />

        {/* Stats bar */}
        <div className="shrink-0 px-2 md:px-3 pt-2 pb-1">
          <StatsBar swarmStatus={swarmStatus} portfolio={portfolio} />
        </div>

        {/* ═══ MOBILE LAYOUT: scrollable single column ═══ */}
        <div className="flex-1 min-h-0 md:hidden overflow-y-auto touch-scroll mobile-pb px-2 pb-3 space-y-2">
          {/* Regime + Controls (compact) */}
          <div className="min-h-[180px]">
            <SideSummary swarmStatus={swarmStatus} agents={agents} onAction={handleSwarmToggle} readOnly={readOnly} />
          </div>

          {/* NAV Chart */}
          <div className="h-[220px]">
            <NavChart currentEquity={Number(portfolio?.equity ?? 0)} />
          </div>

          {/* Positions */}
          <div className="min-h-[200px]">
            <PositionsPanel positions={(portfolio?.open_positions as unknown[]) ?? []} onClose={load} readOnly={readOnly} />
          </div>

          {/* Market Feed */}
          <div className="min-h-[200px]">
            <MarketFeed feed={feed} />
          </div>

          {/* Trade Log */}
          <div className="min-h-[200px]">
            <TradeLog trades={trades} />
          </div>
        </div>

        {/* ═══ DESKTOP LAYOUT: original 12-col grid ═══ */}
        <div className="hidden md:grid flex-1 min-h-0 px-3 pb-3 grid-cols-12 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] gap-2 overflow-hidden">
          {/* Left: Market Feed — full height */}
          <div className="col-span-2 row-span-2 min-h-0">
            <MarketFeed feed={feed} />
          </div>

          {/* Top center: Positions — wide with full detail */}
          <div className="col-span-8 row-span-1 min-h-0">
            <PositionsPanel positions={(portfolio?.open_positions as unknown[]) ?? []} onClose={load} readOnly={readOnly} />
          </div>

          {/* Top right: Consolidated Regime + Agents + Controls */}
          <div className="col-span-2 row-span-1 min-h-0">
            <SideSummary swarmStatus={swarmStatus} agents={agents} onAction={handleSwarmToggle} readOnly={readOnly} />
          </div>

          {/* Bottom center: NAV CHART */}
          <div className="col-span-8 row-span-1 min-h-0">
            <NavChart currentEquity={Number(portfolio?.equity ?? 0)} />
          </div>

          {/* Bottom right: Trade Log */}
          <div className="col-span-2 row-span-1 min-h-0">
            <TradeLog trades={trades} />
          </div>
        </div>
      </main>

      <MobileNav />
    </div>
  );
}
