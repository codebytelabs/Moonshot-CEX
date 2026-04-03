"use client";

interface AgentInfo {
  name: string;
  status: string;
  last_run?: number;
  runs?: number;
  errors?: number;
}

interface Props {
  agents: Record<string, unknown> | null;
}

const AGENT_ICONS: Record<string, string> = {
  watcher: "👁",
  analyzer: "🔬",
  context: "🌐",
  bayesian: "🎲",
  execution: "⚡",
  position_manager: "📊",
  risk_manager: "🛡",
  quant_mutator: "🧬",
  bigbrother: "🤖",
};

export default function AgentsPanel({ agents }: Props) {
  const agentList: AgentInfo[] = agents
    ? Object.entries(agents).map(([name, data]) => ({
        name,
        ...((data as Record<string, unknown>) ?? {}),
        status: (data as Record<string, unknown>)?.status as string ?? "unknown",
      }))
    : [];

  return (
    <div className="h-full panel flex flex-col overflow-hidden">
      <div className="px-3 pt-2.5 pb-1.5 border-b border-white/5 shrink-0 flex items-center justify-between">
        <span className="text-[10px] font-semibold mono text-cyan-500 tracking-widest uppercase">Agents</span>
        <span className="text-[10px] mono text-slate-600">
          {agentList.filter((a) => a.status === "ok").length}/{agentList.length} healthy
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-1 min-h-0">
        {agentList.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-700">
            <span className="text-2xl">🤖</span>
            <span className="text-[10px] mono mt-1">No agent data</span>
          </div>
        ) : (
          <div className="space-y-0.5">
            {agentList.map((agent) => {
              const ok = agent.status === "ok" || agent.status === "idle";
              const err = agent.status === "error";
              return (
                <div key={agent.name} className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/3">
                  <span className="text-sm">{AGENT_ICONS[agent.name] ?? "⚙"}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] mono text-slate-300 capitalize">{agent.name.replace(/_/g, " ")}</p>
                    {agent.runs !== undefined && (
                      <p className="text-[8px] mono text-slate-600">
                        {agent.runs} runs · {agent.errors ?? 0} err
                      </p>
                    )}
                  </div>
                  <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] mono uppercase ${
                    ok ? "text-green-400 bg-green-500/10" : err ? "text-red-400 bg-red-500/10" : "text-amber-400 bg-amber-500/10"
                  }`}>
                    <div className={`w-1 h-1 rounded-full ${ok ? "bg-green-400" : err ? "bg-red-400" : "bg-amber-400"}`} />
                    {agent.status}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
