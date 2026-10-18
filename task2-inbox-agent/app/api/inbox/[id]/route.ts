import { NextResponse } from "next/server";
import { loadEmails } from "@/src/dataset";
import { loadEnv, redactSecrets, requireEnv } from "@/src/env";
import { maskPii } from "@/src/pii";
import { isFailure, runEmail } from "@/src/pipeline";
import { noteFailedCheck } from "@/src/review";
import { loadDraft, openOutputStore, saveDraft } from "@/src/store";

export const runtime = "nodejs";

type RouteContext = { params: Promise<{ id: string }> };

function maskedDraft(output: NonNullable<ReturnType<typeof loadDraft>>) {
  return {
    ...output,
    request_summary: maskPii(output.request_summary),
    suggested_reply: maskPii(output.suggested_reply),
    draft_before_claim_check: maskPii(output.draft_before_claim_check),
    evidence_text: maskPii(output.evidence_text),
    failure_reason: output.failure_reason ? maskPii(output.failure_reason) : null,
    unsupported_claims: output.unsupported_claims.map((claim) => ({
      ...claim,
      text: maskPii(claim.text),
      replacement: claim.replacement ? maskPii(claim.replacement) : undefined,
    })),
  };
}

export async function GET(_request: Request, context: RouteContext) {
  const { id } = await context.params;
  const email = loadEmails().find((item) => item.id === id);
  if (!email) return NextResponse.json({ error: "Email not found." }, { status: 404 });
  const draft = loadDraft(openOutputStore(), id);
  return NextResponse.json({
    email: {
      id: email.id,
      subject: maskPii(email.subject),
      body: maskPii(email.body),
      held_out: email.held_out,
    },
    draft: draft ? maskedDraft(draft) : null,
  });
}

export async function POST(_request: Request, context: RouteContext) {
  const { id } = await context.params;
  const email = loadEmails().find((item) => item.id === id);
  if (!email) return NextResponse.json({ error: "Email not found." }, { status: 404 });
  const env = loadEnv();
  try {
    requireEnv(env);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Missing configuration.";
    return NextResponse.json({ error: maskPii(redactSecrets(message, env)) }, { status: 500 });
  }
  const row = await runEmail(env, email);
  if (isFailure(row)) {
    return NextResponse.json(
      { error: maskPii(redactSecrets(row.message, env)), stage: row.stage },
      { status: 502 },
    );
  }
  const db = openOutputStore();
  saveDraft(db, row);
  if (!row.claim_check_passed || !row.quality_check_passed) {
    noteFailedCheck(db, row.category);
  }
  return NextResponse.json({
    email: {
      id: email.id,
      subject: maskPii(email.subject),
      body: maskPii(email.body),
      held_out: email.held_out,
    },
    draft: maskedDraft(row),
  });
}
