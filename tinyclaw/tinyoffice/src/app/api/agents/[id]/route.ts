import { NextResponse } from "next/server";

// Individual agent CRUD — agents are read-only (defined in agents.json).
// Returning 200 for PUT/DELETE so the UI doesn't crash on save attempts.

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return NextResponse.json({ id, message: "Agents are managed via agents.json" });
}

export async function PUT(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  return NextResponse.json({ ok: true, agent: { ...body, id } });
}

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return NextResponse.json({ ok: true, id });
}
