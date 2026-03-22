"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { apiFetch } from "@/lib/api";

interface AgentDetail {
  status?: string;
  runs?: number;
  errors?: number;
  last_run?: number;
  last_output?: Record<string, unknown>;
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

const AGENT_META: Record<string, { icon: string; description: string }> = {
  watcher:          { icon: "👁",  description: "Scans all pairs by volume & momentum score" },
  analyzer:         { icon: "🔬", description: "Multi-timeframe TA — RSI, MACD, EMA, ATR, S/R" },
  context:          { icon: "🌐", description: "LLM-powered sentiment & catalyst enrichment" },
  bayesian:         { icon: "🎲", description: "Probabilistic buy/hold with online prior updates" },
  execution:        { icon: "⚡", description: "Market order placement with retries" },
  position_manager: { icon: "📊", description: "Tiered exits, trailing stop, time exits" },
  risk_manager:     { icon: "🛡",  description: "Kelly sizing, exposure limits, drawdown breakers" },
  quant_mutator:    { icon: "🧬", description: "Adaptive threshold self-tuning" },
  bigbrother:       { icon: "🤖", description: "Regime detection & mode management" },
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<Record<string, AgentDetail>>({});

  useEffect(() => {
    const load = async () => {
      try {
        const data = await apiFetch("/api/agents");
        setAgents((data.agents ?? data) as Record<string, AgentDetail>);
      } catch (e) {
        console.error(e);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  interface AgentRow {
    name: string;
    status?: string;
    runs?: number;
    errors?: number;
    last_run?: number;
  }

  const loaded = Object.entries(agents).map(([agentName, data]) => ({
    name: agentName,
    status: data.status,
    runs: data.runs,
    errors: data.errors,
    last_run: data.last_run,
  } as AgentRow));

  const displayList: AgentRow[] =
    loaded.length > 0
      ? loaded
      : Object.keys(AGENT_META).map((k) => ({ name: k, status: "unknown" }));

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 flex items-center px-4 gap-3">
          <span className="text-xs font-bold tracking-[0.25em] uppercase neon-text-cyan mono">Agents</span>
          <span className="text-[10px] mono text-slate-600">
            {displayList.filter((a) => a.status === "ok" || a.status === "idle").length}/{displayList.length} healthy
          </span>
        </header>

        <div className="p-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {displayList.map((agent) => {
            const meta = AGENT_META[agent.name] ?? { icon: "⚙", description: "" };
            const ok = agent.status === "ok" || agent.status === "idle";
            const err = agent.status === "error";
            return (
              <div key={agent.name} className="panel p-4">
                <div className="flex items-start gap-3">
                  <span className="text-2xl">{meta.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-xs mono font-semibold text-slate-200 capitalize">
                        {agent.name.replace(/_/g, " ")}
                      </h3>
                      <span className={`text-[9px] mono px-1.5 py-0.5 rounded border ${
                        ok ? "text-green-400 bg-green-500/10 border-green-500/20" :
                        err ? "text-red-400 bg-red-500/10 border-red-500/20" :
                        "text-amber-400 bg-amber-500/10 border-amber-500/20"
                      }`}>
                        {agent.status?.toUpperCase() ?? "UNKNOWN"}
                      </span>
                    </div>
                    <p className="text-[9px] mono text-slate-600 mt-0.5">{meta.description}</p>

                    {(agent.runs !== undefined || agent.errors !== undefined) && (
                      <div className="flex gap-3 mt-2">
                        {agent.runs !== undefined && (
                          <div className="text-[9px] mono text-slate-500">
                            <span className="text-slate-400">{agent.runs}</span> runs
                          </div>
                        )}
                        {(agent.errors ?? 0) > 0 && (
                          <div className="text-[9px] mono text-red-400">
                            {agent.errors} errors
                          </div>
                        )}
                        {agent.last_run && (
                          <div className="text-[9px] mono text-slate-600">
                            {new Date(agent.last_run * 1000).toLocaleTimeString()}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}
