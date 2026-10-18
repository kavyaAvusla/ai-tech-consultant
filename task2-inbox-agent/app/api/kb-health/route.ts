import { NextResponse } from "next/server";
import { loadEnv } from "@/src/env";

export const runtime = "nodejs";

export async function GET() {
  const env = loadEnv();
  try {
    const response = await fetch(`${env.kbApiUrl}/health`, { signal: AbortSignal.timeout(4000) });
    if (!response.ok) {
      return NextResponse.json({
        available: false,
        message: "Knowledge service unavailable",
      });
    }
    return NextResponse.json({ available: true, message: "Knowledge service is responding." });
  } catch {
    return NextResponse.json({
      available: false,
      message: "Knowledge service unavailable",
    });
  }
}
