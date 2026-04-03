/**
 * GET  /api/tasks    — List tasks
 * POST /api/tasks    — Create task
 * PUT  /api/tasks/reorder — Reorder tasks
 *
 * Tasks are stored in-memory for now (resets on server restart).
 * For persistence add a JSON file or MongoDB collection.
 */
import { NextResponse } from "next/server";

// Seed with a few starter tasks relevant to the trading system.
const DEFAULT_TASKS = [
  {
    id: "1",
    title: "Monitor underwater positions",
    description: "Review all open positions with PnL < -5% and ensure stop-losses are triggered appropriately.",
    status: "in_progress",
    assignee: "trading-monitor",
    assigneeType: "agent",
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: "2",
    title: "Analyse strategy win rate",
    description: "Pull last 50 closed trades and compute win rate, profit factor, and avg hold time.",
    status: "backlog",
    assignee: "trade-analyst",
    assigneeType: "agent",
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: "3",
    title: "Verify ghost-close fix",
    description: "Confirm that sub-minimum dust positions are ghost-closed in a single attempt without retrying.",
    status: "done",
    assignee: "trading-monitor",
    assigneeType: "agent",
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
];

// In-memory store (shared across requests in the same Next.js process)
const tasks = [...DEFAULT_TASKS];

export async function GET() {
  return NextResponse.json(tasks);
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const task = {
    id: String(Date.now()),
    title: body.title ?? "New Task",
    description: body.description ?? "",
    status: body.status ?? "backlog",
    assignee: body.assignee ?? "",
    assigneeType: body.assigneeType ?? "",
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  tasks.push(task);
  return NextResponse.json({ ok: true, task });
}
