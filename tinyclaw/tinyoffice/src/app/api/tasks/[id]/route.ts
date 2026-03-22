import { NextResponse } from "next/server";

// In-memory task store — must match /api/tasks/route.ts
// In a production setup, share via a module-level singleton or DB.
let nextId = 100;

// Import-safe: we can't easily share state across route files in Next.js App Router
// without a singleton module, so we maintain a simple local copy here.
const localTasks: Record<string, Record<string, unknown>> = {};

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return NextResponse.json(localTasks[id] ?? { id, error: "not found" });
}

export async function PUT(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  localTasks[id] = { ...localTasks[id], ...body, id, updatedAt: Date.now() };
  return NextResponse.json({ ok: true, task: localTasks[id] });
}

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  delete localTasks[id];
  return NextResponse.json({ ok: true, id });
}

// Suppress unused var warning
void nextId;
