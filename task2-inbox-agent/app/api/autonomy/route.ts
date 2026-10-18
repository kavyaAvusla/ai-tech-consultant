import { NextResponse } from "next/server";
import { z } from "zod";
import { loadEnv, redactSecrets } from "@/src/env";
import { maskPii } from "@/src/pii";
import { setTrialEnabled } from "@/src/review";
import { categorySchema } from "@/src/schema";
import { listCategoryStats, openOutputStore } from "@/src/store";
import { trialAllowed } from "@/src/quality";

export const runtime = "nodejs";

const bodySchema = z.object({
  category: categorySchema,
  enabled: z.boolean(),
});

export async function GET() {
  return NextResponse.json({
    autonomy: listCategoryStats(openOutputStore(), (category) => !trialAllowed(category)),
  });
}

export async function POST(request: Request) {
  const env = loadEnv();
  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Choose a category and a trial state." }, { status: 400 });
  }
  try {
    const autonomy = setTrialEnabled(openOutputStore(), parsed.data.category, parsed.data.enabled);
    return NextResponse.json({ autonomy });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not change the trial.";
    return NextResponse.json({ error: maskPii(redactSecrets(message, env)) }, { status: 400 });
  }
}
