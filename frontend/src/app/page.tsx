"use client";
import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { useSwarmSocket } from "@/lib/useWebSocket";
import Sidebar from "@/components/Sidebar";
import StatsBar from "@/components/StatsBar";
import MarketFeed from "@/components/MarketFeed";
import PositionsPanel from "@/components/PositionsPanel";
import TradeLog from "@/components/TradeLog";
import RegimePanel from "@/components/RegimePanel";
import AgentsPanel from "@/components/AgentsPanel";
import SwarmControl from "@/components/SwarmControl";
import NavChart from "@/components/NavChart";

export default function Dashboard() {
  const [swarmStatus, setSwarmStatus] = useState<Record<string, unknown> | null>(null);
  const [portfolio, setPortfolio] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState<Record<string, unknown> | null>(null);
  const [feed, setFeed] = useState<Record<string, unknown> | null>(null);
  const [trades, setTrades] = useState<unknown[]>([]);
  const [mounted, setMounted] = useState(false);
  const [currentTime, setCurrentTime] = useState("");
  const { messages, connected } = useSwarmSocket();

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
        {/* Header */}
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 backdrop-blur flex items-center px-4 gap-3">
          <span className="text-xs font-bold tracking-[0.25em] uppercase neon-text-cyan mono">
            MOONSHOT-CEX
          </span>
          <span className="text-[10px] mono text-slate-600">
            {swarmStatus?.exchange_mode === "paper"
              ? "// PAPER TRADING"
              : swarmStatus?.exchange_mode === "demo"
              ? "// DEMO MODE"
              : "// LIVE"}
          </span>
          <div className="ml-auto flex items-center gap-4">
            <span className="text-[10px] mono text-slate-500">
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
              {connected ? "LIVE" : "DISCONNECTED"}
            </div>
            <span className="text-[10px] mono text-slate-600">
              {mounted ? currentTime : "--:--:--"}
            </span>
          </div>
        </header>

        {/* Stats bar */}
        <div className="shrink-0 px-3 pt-2 pb-1">
          <StatsBar swarmStatus={swarmStatus} portfolio={portfolio} />
        </div>

        {/* Main grid — NAV chart prominent */}
        <div className="flex-1 min-h-0 px-3 pb-3 grid grid-cols-12 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] gap-2 overflow-hidden">
          {/* Left: Market Feed — full height */}
          <div className="col-span-2 row-span-2 min-h-0">
            <MarketFeed feed={feed} />
          </div>

          {/* Top center: Positions */}
          <div className="col-span-5 row-span-1 min-h-0">
            <PositionsPanel positions={(portfolio?.open_positions as unknown[]) ?? []} />
          </div>

          {/* Top right: Regime */}
          <div className="col-span-2 row-span-1 min-h-0">
            <RegimePanel swarmStatus={swarmStatus} />
          </div>

          {/* Top far-right: Swarm Control */}
          <div className="col-span-1 row-span-1 min-h-0">
            <SwarmControl swarmStatus={swarmStatus} onAction={handleSwarmToggle} />
          </div>

          {/* Top far-right: Agents compact */}
          <div className="col-span-2 row-span-1 min-h-0">
            <AgentsPanel agents={agents} />
          </div>

          {/* Bottom center: NAV CHART — big and prominent */}
          <div className="col-span-7 row-span-1 min-h-0">
            <NavChart currentEquity={Number(portfolio?.equity ?? 0)} />
          </div>

          {/* Bottom right: Trade Log */}
          <div className="col-span-3 row-span-1 min-h-0">
            <TradeLog trades={trades} />
          </div>
        </div>
      </main>
    </div>
  );
}
