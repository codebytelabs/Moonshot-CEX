/**
 * GET /api/agents  — Returns the three Moonshot-CEX TinyClaw agents
 * in the AgentConfig shape that TinyOffice expects.
 *
 * PUT /api/agents  — No-op (agents are read-only for now).
 */
import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

// Resolve agents.json: cwd() = tinyclaw/tinyoffice, so go up one level to tinyclaw/
const AGENTS_FILE = path.resolve(process.cwd(), "../agents.json");


function loadAgents(): Record<string, object> {
  try {
    const raw = fs.readFileSync(AGENTS_FILE, "utf-8");
    const parsed = JSON.parse(raw) as { agents: Array<{ id: string; name: string; model: string; system_prompt?: string; role?: string; enabled?: boolean }> };
    // Convert array → Record<id, AgentConfig>
    const result: Record<string, object> = {};
    for (const agent of parsed.agents ?? []) {
      result[agent.id] = {
        name: agent.name,
        provider: "openrouter",
        model: agent.model,
        working_directory: "/Users/vishnuvardhanmedara/Moonshot-CEX",
        system_prompt: agent.system_prompt ?? "",
        // Extra fields TinyOffice may display
        role: agent.role ?? "",
        enabled: agent.enabled ?? true,
      };
    }
    return result;
  } catch {
    return {};
  }
}

export async function GET() {
  return NextResponse.json(loadAgents());
}

export async function PUT() {
  // Agents are managed via agents.json — return current state
  return NextResponse.json({ ok: true, agents: loadAgents() });
}
