/**
 * GET /api/queue/status — Returns queue metrics (proxied from port 8000 or mocked).
 * TinyOffice displays this as "Inbox / Processing / Outgoing" counters.
 */
import { NextResponse } from "next/server";

const BACKEND = "http://localhost:8000";

export async function GET() {
  try {
    // Try to derive queue-like metrics from the trading backend
    const [swarmRes, posRes] = await Promise.allSettled([
      fetch(`${BACKEND}/api/swarm/status`, { signal: AbortSignal.timeout(3000) }),
      fetch(`${BACKEND}/api/positions`, { signal: AbortSignal.timeout(3000) }),
    ]);

    const swarm = swarmRes.status === "fulfilled" && swarmRes.value.ok
      ? await swarmRes.value.json()
      : {};
    const positions = posRes.status === "fulfilled" && posRes.value.ok
      ? await posRes.value.json()
      : [];

    const openPositions = Array.isArray(positions) ? positions.length : 0;
    const cycleCount = swarm?.cycle ?? 0;

    return NextResponse.json({
      incoming: cycleCount % 10,        // watcher pipeline candidates (approximation)
      processing: openPositions,         // positions being managed
      outgoing: 0,                       // completed in last cycle
      activeConversations: openPositions,
    });
  } catch {
    return NextResponse.json({ incoming: 0, processing: 0, outgoing: 0, activeConversations: 0 });
  }
}
