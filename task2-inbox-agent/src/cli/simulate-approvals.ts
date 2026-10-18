import { loadEnv, redactSecrets, requireEnv } from "../env.js";
import { logSafe, maskPii } from "../pii.js";
import { recordReview } from "../review.js";
import type { PipelineOutput, SupportEmail } from "../schema.js";
import { openOutputStore, listCategoryStats } from "../store.js";
import { trialAllowed } from "../quality.js";

const DRAFT_TEXT = [
  "Hello,",
  "",
  "Open My Content, then SEO Templates. On the SEO Settings tab, edit the Social Media Sharing fields and click Save This Page.",
  "",
  "https://support.brilliantdirectories.com/support/solutions/articles/5000682655-how-to-edit-the-seo-for-social-media-sharing-for-seo-templates",
].join("\n");

function simulatedEmail(index: number): SupportEmail {
  return {
    id: `sim-how-${String(index).padStart(2, "0")}`,
    subject: "How do I edit social sharing on an SEO template?",
    body: "Please tell me where the Social Media Sharing fields are on an SEO template. This is a simulated review for the autonomy counter.",
    expected_category: "how_to",
    important_facts: ["Simulated unedited approval"],
    expected_behavior: "Count as an identical send.",
    risk_level: "low",
    expected_source_url:
      "https://support.brilliantdirectories.com/support/solutions/articles/5000682655-how-to-edit-the-seo-for-social-media-sharing-for-seo-templates",
    held_out: false,
  };
}

function simulatedDraft(email: SupportEmail): PipelineOutput {
  return {
    email_id: email.id,
    prompt_version: "v1",
    category: "how_to",
    urgency: "low",
    request_summary: "Customer asks where to edit social sharing fields on an SEO template.",
    suggested_reply: DRAFT_TEXT,
    sources: [email.expected_source_url],
    evidence: "strong",
    evidence_text: "Navigate to My Content > SEO Templates. Update the Social Media Sharing section. Click Save This Page.",
    escalation_id: null,
    risk_level: "low",
    needs_human_approval: false,
    next_action: "Follow up within 2 business days if the customer says the steps did not work.",
    kb_status: "ok",
    failure_reason: null,
    prompt_injection_detected: false,
    model_name: "simulated-identical-draft",
    draft_before_claim_check: DRAFT_TEXT,
    unsupported_claims: [],
    claim_check_passed: true,
    quality_check_passed: true,
  };
}

function main(): void {
  const env = loadEnv();
  requireEnv(env);
  const db = openOutputStore();
  let created = 0;
  let duplicates = 0;
  for (let index = 1; index <= 20; index += 1) {
    const email = simulatedEmail(index);
    const result = recordReview(db, {
      email,
      draft: simulatedDraft(email),
      outcome: "approved",
      idempotencyKey: `sim-approval-how_to-${index}`,
    });
    if (result.duplicate) duplicates += 1;
    else created += 1;
  }
  const stats = listCategoryStats(db, (category) => !trialAllowed(category));
  const howTo = stats.find((row) => row.category === "how_to");
  logSafe(
    maskPii(
      redactSecrets(
        `simulated identical approvals created=${created} already_sent=${duplicates} how_to_count=${howTo?.consecutive_identical ?? 0} eligible=${howTo?.eligible ? "yes" : "no"} trial=${howTo?.trial_enabled ? "on" : "off"}`,
        env,
      ),
    ),
  );
  if (howTo?.eligible) {
    logSafe("how_to is eligible for a controlled autonomy trial. The trial stays off until you enable it in the inbox.");
  }
}

main();
