/**
 * GET /api/events/stream — Server-Sent Events stream bridging Moonshot WebSocket
 * to TinyOffice's SSE subscription format.
 *
 * TinyOffice subscribes to event types:
 *   connected, message_received, agent_routed, chain_step_start, chain_step_done,
 *   chain_handoff, team_chain_start, team_chain_end, response_ready,
 *   processor_start, message_enqueued
 *
 * We poll the Moonshot backend every 5 seconds and emit synthetic events.
 */
import { NextResponse } from "next/server";

const BACKEND = "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET() {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      // Send initial connected event
      const send = (type: string, data: Record<string, unknown>) => {
        const payload = JSON.stringify({ type, timestamp: Date.now(), ...data });
        controller.enqueue(encoder.encode(`event: ${type}\ndata: ${payload}\n\n`));
      };

      send("connected", { message: "Moonshot-CEX bridge connected" });

      // Poll every 5 seconds and emit status events
      let running = true;
      const interval = setInterval(async () => {
        if (!running) return;
        try {
          const res = await fetch(`${BACKEND}/api/swarm/status`, {
            signal: AbortSignal.timeout(2000),
          });
          if (res.ok) {
            const status = await res.json() as Record<string, unknown>;
            send("chain_step_done", {
              agent: "trading-monitor",
              message: `Cycle ${status.cycle ?? "?"}. Running: ${status.running}. Regime: ${status.regime ?? "unknown"}`,
              result: status,
            });
          }
        } catch {
          // Backend temporarily unreachable — don't close the stream
        }
      }, 5000);

      // Clean up when client disconnects
      return () => {
        running = false;
        clearInterval(interval);
      };
    },
  });

  return new NextResponse(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
