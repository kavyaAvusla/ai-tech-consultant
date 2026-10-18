import { NextResponse } from "next/server";
import { z } from "zod";
import { loadEmails } from "@/src/dataset";
import { loadEnv, redactSecrets } from "@/src/env";
import { maskPii } from "@/src/pii";
import { recordReview } from "@/src/review";
import { loadDraft, openOutputStore } from "@/src/store";

export const runtime = "nodejs";

const bodySchema = z.object({
  emailId: z.string().min(1),
  outcome: z.enum(["approved", "edited", "rejected", "needs_expert"]),
  reason: z.string().optional(),
  reply: z.string().optional(),
  idempotencyKey: z.string().min(8).max(200),
});

export async function POST(request: Request) {
  const env = loadEnv();
  let json: unknown;
  try {
    json = await request.json();
  } catch {
    return NextResponse.json({ error: "The review body was not JSON." }, { status: 400 });
  }
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ error: "Review request is missing a field." }, { status: 400 });
  }
  const email = loadEmails().find((item) => item.id === parsed.data.emailId);
  const draft = email ? loadDraft(openOutputStore(), email.id) : null;
  if (!email || !draft) {
    return NextResponse.json({ error: "Draft a reply before reviewing it." }, { status: 404 });
  }
  try {
    const result = recordReview(openOutputStore(), {
      email,
      draft,
      outcome: parsed.data.outcome,
      reason: parsed.data.reason,
      reply: parsed.data.reply,
      idempotencyKey: parsed.data.idempotencyKey,
    });
    return NextResponse.json({
      duplicate: result.duplicate,
      sent: result.sent
        ? { id: result.sent.id, email_id: result.sent.email_id, created_at: result.sent.created_at }
        : null,
      feedback_id: result.feedback_id,
      autonomy: result.autonomy,
      message: result.duplicate
        ? "Already sent (simulated). This retry did not create a second message."
        : result.sent
          ? "Simulated send stored in the outbox."
          : "Marked for an expert. Nothing was sent.",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Review failed.";
    return NextResponse.json({ error: maskPii(redactSecrets(message, env)) }, { status: 400 });
  }
}
