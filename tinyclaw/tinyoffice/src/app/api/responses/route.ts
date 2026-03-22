/**
 * GET /api/responses — Returns recent trade events formatted as TinyClaw responses.
 * Bridges the Moonshot feed endpoint to TinyOffice's ResponseData shape.
 */
import { NextResponse } from "next/server";

const BACKEND = "http://localhost:8000";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") ?? 20);

  try {
    const res = await fetch(`${BACKEND}/api/feed?limit=${limit}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) throw new Error("feed unavailable");
    const feed = await res.json() as Array<Record<string, unknown>>;

    const responses = (Array.isArray(feed) ? feed : []).slice(0, limit).map((item) => ({
      channel: "trading-feed",
      sender: String(item.agent ?? item.source ?? "system"),
      message: String(item.summary ?? item.message ?? item.reason ?? JSON.stringify(item)),
      originalMessage: "",
      timestamp: Number(item.ts ?? item.timestamp ?? Date.now()),
      messageId: String(item.id ?? Math.random()),
      agent: String(item.agent ?? "trading-monitor"),
    }));

    return NextResponse.json(responses);
  } catch {
    return NextResponse.json([]);
  }
}
