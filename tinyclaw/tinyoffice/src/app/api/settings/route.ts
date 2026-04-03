/**
 * GET /api/settings — Returns TinyClaw settings including workspace, agents, and teams.
 * PUT /api/settings — No-op (write to agents.json instead).
 */
import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

const AGENTS_FILE = path.resolve(process.cwd(), "../agents.json");


function loadAgentsAsRecord(): Record<string, object> {
  try {
    const raw = fs.readFileSync(AGENTS_FILE, "utf-8");
    const parsed = JSON.parse(raw) as { agents: Array<{ id: string; name: string; model: string; system_prompt?: string }> };
    const result: Record<string, object> = {};
    for (const a of parsed.agents ?? []) {
      result[a.id] = {
        name: a.name,
        provider: "openrouter",
        model: a.model,
        working_directory: "/Users/vishnuvardhanmedara/Moonshot-CEX",
        system_prompt: a.system_prompt ?? "",
      };
    }
    return result;
  } catch {
    return {};
  }
}

export async function GET() {
  return NextResponse.json({
    workspace: {
      path: "/Users/vishnuvardhanmedara/Moonshot-CEX",
      name: "Moonshot-CEX",
    },
    models: {
      provider: "openrouter",
      opencode: { model: "google/gemini-2.5-flash-lite-preview-09-2025" },
    },
    agents: loadAgentsAsRecord(),
    teams: {
      "moonshot-trading": {
        name: "Moonshot Trading",
        agents: ["trading-monitor", "trading-commander", "trade-analyst"],
        leader_agent: "trading-commander",
      },
    },
    channels: { enabled: [] },
    monitoring: { heartbeat_interval: 30 },
  });
}

export async function PUT(req: Request) {
  const body = await req.json().catch(() => ({}));
  // Settings writes are no-ops — configuration lives in agents.json
  return NextResponse.json({ ok: true, settings: body });
}
