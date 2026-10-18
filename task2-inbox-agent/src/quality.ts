import type { Category } from "./schema.js";
import { PROMISE_IN_TEXT, DATE_IN_TEXT } from "./schema.js";

export type QualityResult = {
  passed: boolean;
  reasons: string[];
};

export function normalizeReply(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function repliesMatch(generated: string, sent: string): boolean {
  return normalizeReply(generated) === normalizeReply(sent) && normalizeReply(generated).length > 0;
}

const LEGAL_OR_SECURITY =
  /\b(lawsuit|attorney|lawyer|legal action|sue us|two-factor|2fa|authenticator|password reset|account was hacked|compromised account)\b/i;

export function isLegalOrAccountSecurity(text: string): boolean {
  return LEGAL_OR_SECURITY.test(text);
}

/** Refunds, legal topics, account security, and complaints cannot enter an autonomy trial. */
export function trialAllowed(category: Category): boolean {
  return category !== "refund_cancellation" && category !== "complaint";
}

export function qualityCheck(input: {
  reply: string;
  evidence: "strong" | "weak" | "unavailable";
  kbOk: boolean;
}): QualityResult {
  const reasons: string[] = [];
  if (!input.kbOk) {
    if (input.reply.trim().length > 0) reasons.push("A reply was drafted while the knowledge service was down.");
    return { passed: reasons.length === 0, reasons };
  }
  if (input.reply.trim().length === 0) reasons.push("The draft is empty.");
  if (PROMISE_IN_TEXT.test(input.reply) || DATE_IN_TEXT.test(input.reply)) {
    reasons.push("The draft promises a refund, a price, a delivery date, or a calendar date.");
  }
  if (input.evidence === "weak" && !/expert/i.test(input.reply)) {
    reasons.push("Weak evidence must say we will check with an expert.");
  }
  return { passed: reasons.length === 0, reasons };
}
