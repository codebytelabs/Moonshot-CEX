/**
 * PUT /api/tasks/reorder  — Accepts { columns: Record<status, id[]> }
 */
import { NextResponse } from "next/server";

export async function PUT(req: Request) {
  const body = await req.json().catch(() => ({}));
  // In-memory state — reorder is a no-op without shared store
  return NextResponse.json({ ok: true, columns: body.columns ?? {} });
}
