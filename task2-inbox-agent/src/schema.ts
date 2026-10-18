import { z } from "zod";

export const categorySchema = z.enum([
  "how_to",
  "troubleshooting",
  "project_request",
  "refund_cancellation",
  "complaint",
  "quote_request",
  "follow_up",
]);

export type Category = z.infer<typeof categorySchema>;

export const riskSchema = z.enum(["low", "medium", "high"]);
export type RiskLevel = z.infer<typeof riskSchema>;

export const emailSchema = z.object({
  id: z.string().min(1),
  subject: z.string().min(1),
  body: z.string().min(1),
  expected_category: categorySchema,
  important_facts: z.array(z.string().min(1)).min(1),
  expected_behavior: z.string().min(1),
  risk_level: riskSchema,
  expected_source_url: z.string().min(1),
  held_out: z.boolean(),
});

export type SupportEmail = z.infer<typeof emailSchema>;

export const EXPECTED_COUNTS: Record<Category, number> = {
  how_to: 12,
  troubleshooting: 10,
  project_request: 6,
  refund_cancellation: 6,
  complaint: 6,
  quote_request: 5,
  follow_up: 5,
};

export const kbStatusSchema = z.enum([
  "ok",
  "timeout",
  "unauthorized",
  "billing",
  "http_error",
  "network",
  "invalid_response",
]);

export const pipelineOutputSchema = z
  .object({
    email_id: z.string().min(1),
    prompt_version: z.string().min(1),
    category: categorySchema,
    urgency: z.enum(["low", "normal", "high"]),
    request_summary: z.string().min(1).max(600),
    suggested_reply: z.string().max(4000),
    sources: z.array(z.string()),
    evidence: z.enum(["strong", "weak", "unavailable"]),
    escalation_id: z.number().int().positive().nullable(),
    risk_level: riskSchema,
    needs_human_approval: z.boolean(),
    next_action: z.string().min(1).max(300),
    kb_status: kbStatusSchema,
    failure_reason: z.string().nullable(),
    prompt_injection_detected: z.boolean(),
    model_name: z.string().min(1),
    evidence_text: z.string().max(8000),
    draft_before_claim_check: z.string().max(8000),
    unsupported_claims: z.array(
      z.object({
        text: z.string(),
        action: z.enum(["removed", "rewritten"]),
        replacement: z.string().optional(),
      }),
    ),
    claim_check_passed: z.boolean(),
    quality_check_passed: z.boolean(),
  })
  .superRefine((value, ctx) => {
    if (DATE_IN_TEXT.test(value.next_action)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["next_action"],
        message: "next_action must be a timeframe, not a calendar date",
      });
    }
    if (APPROVAL_CATEGORIES.has(value.category) && !value.needs_human_approval) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["needs_human_approval"],
        message: "this category always needs human approval",
      });
    }
    if (value.kb_status !== "ok") {
      if (!value.failure_reason) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["failure_reason"],
          message: "a Knowledge Brain failure needs a reason",
        });
      }
      if (value.suggested_reply.trim().length > 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["suggested_reply"],
          message: "do not draft a reply when the knowledge service failed",
        });
      }
    }
    if (
      value.kb_status === "ok" &&
      value.evidence === "weak" &&
      !/expert/i.test(value.suggested_reply)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["suggested_reply"],
        message: "weak evidence must say we will check with an expert",
      });
    }
    if (PROMISE_IN_TEXT.test(value.suggested_reply)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["suggested_reply"],
        message: "reply promises a refund, price, delivery date, or unauthorized change",
      });
    }
  });

export type PipelineOutput = z.infer<typeof pipelineOutputSchema>;

export const APPROVAL_CATEGORIES = new Set<Category>([
  "refund_cancellation",
  "quote_request",
  "complaint",
  "project_request",
]);

/** Calendar dates and numeric dates. A timeframe like "1 business day" is allowed. */
export const DATE_IN_TEXT =
  /\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b|\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/i;

export const PROMISE_IN_TEXT =
  /\b(refund (has been|is|was) approved|full refund|your refund of|price is|quoted price|\$\s?\d|deliver(?:ed|y)? on|will be delivered|launch on|go live on|we will (build|ship|implement) (it|this) by)\b/i;
