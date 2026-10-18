import { NextResponse } from "next/server";
import { loadEmails } from "@/src/dataset";
import { loadEnv, redactSecrets } from "@/src/env";
import { maskPii } from "@/src/pii";
import { trialAllowed } from "@/src/quality";
import { listCategoryStats, loadDraft, openOutputStore } from "@/src/store";

export const runtime = "nodejs";

export async function GET() {
  const env = loadEnv();
  const db = openOutputStore();
  const emails = loadEmails().map((email) => {
    const draft = loadDraft(db, email.id);
    return {
      id: email.id,
      subject: maskPii(email.subject),
      held_out: email.held_out,
      has_draft: Boolean(draft),
      category: draft?.category ?? null,
      risk_level: draft?.risk_level ?? null,
      kb_status: draft?.kb_status ?? null,
    };
  });
  return NextResponse.json({
    emails,
    autonomy: listCategoryStats(db, (category) => !trialAllowed(category)),
    model: env.modelName,
    notice: maskPii(redactSecrets("Inbox ready.", env)),
  });
}
