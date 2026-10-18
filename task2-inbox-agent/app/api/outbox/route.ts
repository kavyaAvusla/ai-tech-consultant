import { NextResponse } from "next/server";
import { maskPii } from "@/src/pii";
import { listSent, openOutputStore } from "@/src/store";

export const runtime = "nodejs";

export async function GET() {
  const rows = listSent(openOutputStore()).map((row) => ({
    id: row.id,
    email_id: row.email_id,
    category: row.category,
    body: maskPii(row.body),
    created_at: row.created_at,
    label: "SIMULATED",
  }));
  return NextResponse.json({ label: "SIMULATED", rows });
}
