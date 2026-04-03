/**
 * GET /api/logs — Returns system logs from the Moonshot backend log file.
 * Bridges to /api/feed or reads logs/backend.log directly.
 */
import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const LOG_FILE = path.resolve(process.cwd(), "../../logs/backend.log");


export async function GET(req: Request) {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") ?? 100);

  try {
    const content = fs.readFileSync(LOG_FILE, "utf-8");
    const lines = content
      .split("\n")
      .filter(Boolean)
      .slice(-limit)
      .reverse(); // newest first
    return NextResponse.json({ lines });
  } catch {
    return NextResponse.json({ lines: ["Backend log file not accessible."] });
  }
}
