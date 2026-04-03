/**
 * POST /api/message — Send a message to a specific agent.
 * For now, returns a stub response. In a full integration this would
 * route to an OpenRouter-backed agent runner.
 */
import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  return NextResponse.json({
    ok: true,
    messageId: `msg_${Date.now()}`,
    agent: body.agent ?? "trading-monitor",
    message: body.message ?? "",
    note: "Message received. Agent runtime integration pending.",
  });
}
