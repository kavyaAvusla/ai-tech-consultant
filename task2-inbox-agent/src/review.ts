import { createHash } from "node:crypto";
import type { DatabaseSync } from "node:sqlite";
import { maskPii } from "./pii.js";
import type { PipelineOutput, SupportEmail } from "./schema.js";
import {
  findSent,
  insertFeedback,
  insertSent,
  listCategoryStats,
  nextFeedbackVersion,
  writeCategoryStat,
  type CategoryStat,
  type SentRow,
} from "./store.js";
import { isLegalOrAccountSecurity, repliesMatch, trialAllowed } from "./quality.js";
import type { Category } from "./schema.js";

export type ReviewOutcome = "approved" | "edited" | "rejected" | "needs_expert";

export type ReviewInput = {
  email: SupportEmail;
  draft: PipelineOutput;
  outcome: ReviewOutcome;
  reason?: string;
  reply?: string;
  idempotencyKey?: string;
};

export type ReviewResult = {
  duplicate: boolean;
  sent: SentRow | null;
  feedback_id: number;
  autonomy: CategoryStat[];
};

function requireReason(outcome: ReviewOutcome, reason: string | undefined): string | null {
  if (outcome !== "edited" && outcome !== "rejected") return reason?.trim() || null;
  const text = reason?.trim() ?? "";
  if (text.length < 3) {
    throw new Error("A reason is required when you edit or reject a draft.");
  }
  return text;
}

export function idempotencyKeyFor(input: ReviewInput, finalText: string): string {
  if (input.outcome === "approved") {
    const hash = createHash("sha256")
      .update(`${input.email.id}|${input.draft.prompt_version}|${input.draft.suggested_reply}`)
      .digest("hex")
      .slice(0, 24);
    return `approved:${input.email.id}:${hash}`;
  }
  if (input.idempotencyKey && input.idempotencyKey.trim().length > 0) {
    return input.idempotencyKey.trim();
  }
  const hash = createHash("sha256")
    .update(`${input.email.id}|${input.outcome}|${finalText}`)
    .digest("hex")
    .slice(0, 24);
  return `${input.email.id}:${input.outcome}:${hash}`;
}

export function noteFailedCheck(db: DatabaseSync, category: Category): void {
  const current = listCategoryStats(db, (name) => !trialAllowed(name)).find((row) => row.category === category);
  writeCategoryStat(db, {
    category,
    consecutive_identical: 0,
    eligible: false,
    trial_enabled: false,
  });
  void current;
}

export function recordReview(db: DatabaseSync, input: ReviewInput): ReviewResult {
  const reason = requireReason(input.outcome, input.reason);
  const generated = input.draft.suggested_reply;
  let humanEdited: string | null = null;
  let finalText: string | null = null;

  if (input.outcome === "approved") {
    if (input.draft.kb_status !== "ok" || generated.trim().length === 0) {
      throw new Error("Knowledge service unavailable. Nothing was sent.");
    }
    finalText = generated;
  } else if (input.outcome === "edited" || input.outcome === "rejected") {
    const reply = input.reply?.trim() ?? "";
    if (reply.length < 3) {
      throw new Error(input.outcome === "edited" ? "Write the edited reply before sending." : "Write the replacement before sending.");
    }
    humanEdited = reply;
    finalText = reply;
  }

  const key = finalText ? idempotencyKeyFor(input, finalText) : "";
  const existing = key ? findSent(db, key) : null;
  if (existing) {
    return {
      duplicate: true,
      sent: existing,
      feedback_id: 0,
      autonomy: listCategoryStats(db, (category) => !trialAllowed(category)),
    };
  }
  const now = new Date().toISOString();
  const sent = finalText
    ? insertSent(db, {
        idempotency_key: key,
        email_id: input.email.id,
        category: input.draft.category,
        body: maskPii(finalText),
        created_at: now,
      })
    : null;

  const identical = Boolean(finalText && repliesMatch(generated, finalText));
  const blockedTopic = isLegalOrAccountSecurity(`${input.email.subject}\n${input.email.body}`);
  const claimFailed = !input.draft.claim_check_passed;
  const qualityFailed = !input.draft.quality_check_passed;
  applyAutonomy(db, {
    category: input.draft.category,
    outcome: input.outcome,
    identical,
    blockedTopic,
    claimFailed,
    qualityFailed,
    duplicate: false,
  });

  const feedbackId = insertFeedback(db, {
    version: nextFeedbackVersion(db, input.email.id),
    email_id: input.email.id,
    original_email: maskPii(`Subject: ${input.email.subject}\n\n${input.email.body}`),
    predicted_category: input.draft.category,
    sources_json: JSON.stringify(input.draft.sources),
    generated_draft: maskPii(generated),
    human_edited_reply: humanEdited ? maskPii(humanEdited) : null,
    final_sent_reply: sent ? sent.body : null,
    model_name: input.draft.model_name,
    prompt_version: input.draft.prompt_version,
    approval_outcome: input.outcome,
    reason: reason ? maskPii(reason) : null,
    claim_check_passed: input.draft.claim_check_passed ? 1 : 0,
    quality_check_passed: input.draft.quality_check_passed ? 1 : 0,
    created_at: now,
  });

  return {
    duplicate: Boolean(existing),
    sent,
    feedback_id: feedbackId,
    autonomy: listCategoryStats(db, (category) => !trialAllowed(category)),
  };
}

function applyAutonomy(
  db: DatabaseSync,
  input: {
    category: Category;
    outcome: ReviewOutcome;
    identical: boolean;
    blockedTopic: boolean;
    claimFailed: boolean;
    qualityFailed: boolean;
    duplicate: boolean;
  },
): void {
  const stats = listCategoryStats(db, (category) => !trialAllowed(category));
  const current = stats.find((row) => row.category === input.category);
  let count = current?.consecutive_identical ?? 0;
  let eligible = current?.eligible ?? false;
  let trial = current?.trial_enabled ?? false;
  const reset =
    input.outcome === "edited" ||
    input.outcome === "rejected" ||
    input.claimFailed ||
    input.qualityFailed;
  if (reset) {
    count = 0;
    eligible = false;
    trial = false;
  } else if (input.outcome === "approved" && input.identical && !input.blockedTopic && !input.duplicate) {
    count += 1;
    if (count >= 20 && trialAllowed(input.category)) eligible = true;
  }
  if (!trialAllowed(input.category)) {
    eligible = false;
    trial = false;
  }
  writeCategoryStat(db, {
    category: input.category,
    consecutive_identical: count,
    eligible,
    trial_enabled: trial,
  });
}

export function setTrialEnabled(db: DatabaseSync, category: Category, enabled: boolean): CategoryStat[] {
  if (!trialAllowed(category)) {
    throw new Error("Refund, legal, account security, and serious complaint categories are never eligible.");
  }
  const stats = listCategoryStats(db, (name) => !trialAllowed(name));
  const current = stats.find((row) => row.category === category);
  if (enabled && !current?.eligible) {
    throw new Error("This category is not eligible for a trial yet.");
  }
  writeCategoryStat(db, {
    category,
    consecutive_identical: current?.consecutive_identical ?? 0,
    eligible: current?.eligible ?? false,
    trial_enabled: enabled,
  });
  return listCategoryStats(db, (name) => !trialAllowed(name));
}
