/**
 * GET /api/teams — Returns the Moonshot-CEX trading team.
 */
import { NextResponse } from "next/server";

const TEAMS = {
  "moonshot-trading": {
    name: "Moonshot Trading",
    agents: ["trading-monitor", "trading-commander", "trade-analyst"],
    leader_agent: "trading-commander",
  },
};

export async function GET() {
  return NextResponse.json(TEAMS);
}

export async function PUT() {
  return NextResponse.json({ ok: true, teams: TEAMS });
}
