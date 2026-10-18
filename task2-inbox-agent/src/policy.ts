import type { Category, RiskLevel } from "./schema.js";
import { APPROVAL_CATEGORIES, DATE_IN_TEXT, PROMISE_IN_TEXT } from "./schema.js";

const INJECTION_PATTERN =
  /ignore (all |any |previous |prior )?instructions|disregard (the |all )?(above|previous|rules)|you are now|system prompt|do not mention sources|do not escalate|jailbreak/i;

const RISK_RANK: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };

export function detectPromptInjection(subject: string, body: string): boolean {
  return INJECTION_PATTERN.test(`${subject}\n${body}`);
}

export function questionForKnowledge(subject: string, body: string): string {
  const lines = body.split(/\r?\n/).filter((line) => !INJECTION_PATTERN.test(line));
  const cleaned = lines.join("\n").replace(/\s+/g, " ").trim();
  const text = `${subject.trim()}\n${cleaned}`.trim();
  return text.length > 1800 ? text.slice(0, 1800) : text;
}

const BROKEN_BEHAVIOR =
  /\b(fail(?:s|ed|ing)?|error|broken|timeout|blank page|never arrive|never show)\b/i;

/** A broken behavior outranks a how-to, even when the writer also asks for steps. */
export function adjustCategory(category: Category, subject: string, body: string): Category {
  if (category === "how_to" && BROKEN_BEHAVIOR.test(`${subject}\n${body}`)) {
    return "troubleshooting";
  }
  return category;
}

export function higherRisk(left: RiskLevel, right: RiskLevel): RiskLevel {
  return RISK_RANK[left] >= RISK_RANK[right] ? left : right;
}

export function categoryRiskFloor(category: Category): RiskLevel {
  if (category === "refund_cancellation" || category === "complaint") return "high";
  if (category === "quote_request" || category === "project_request" || category === "troubleshooting") {
    return "medium";
  }
  return "low";
}

export function needsHumanApproval(input: {
  category: Category;
  risk: RiskLevel;
  evidence: "strong" | "weak" | "unavailable";
  kbOk: boolean;
  injection: boolean;
}): boolean {
  if (!input.kbOk) return true;
  if (APPROVAL_CATEGORIES.has(input.category)) return true;
  if (input.evidence !== "strong") return true;
  if (input.risk === "high") return true;
  if (input.injection) return true;
  return false;
}

export function followUpTimeframe(input: {
  category: Category;
  evidence: "strong" | "weak" | "unavailable";
  kbOk: boolean;
  approval: boolean;
}): string {
  if (!input.kbOk) {
    return "Do not send a reply. A person should pick this up within 1 business day.";
  }
  if (input.approval || APPROVAL_CATEGORIES.has(input.category)) {
    return "A person must approve any reply before it is sent. Follow up within 1 business day.";
  }
  if (input.evidence !== "strong") {
    return "Check with an expert and follow up within 1 business day.";
  }
  return "Follow up within 2 business days if the customer says the steps did not work.";
}

export function publicSummary(summary: string, subject: string): string {
  const cleaned = summary
    .replace(DATE_IN_TEXT, "")
    .replace(/\$\s?\d[\d,]*/g, "")
    .replace(INJECTION_PATTERN, "")
    .replace(/\s+/g, " ")
    .trim();
  const usable = cleaned.length >= 12 ? cleaned : subject.trim();
  return usable.slice(0, 400);
}

export function expertReply(summary: string): string {
  return [
    "Hello,",
    "",
    `Thank you for writing about this: ${summary}`,
    "",
    "We do not have a strong match in the support articles, so we will check with an expert before sending any steps. Nothing here is a promise about a refund, a price, a delivery date, or a change to the site.",
    "",
    "A teammate will follow up after that check.",
  ].join("\n");
}

export function groundedReply(answer: string, sources: string[]): string {
  const sourceBlock = sources.length > 0 ? `\n\nSources:\n${sources.map((url) => `- ${url}`).join("\n")}` : "";
  return `Hello,\n\n${answer.trim()}${sourceBlock}\n\nReply if the screen you see does not match these notes.`.trim();
}

export function replyBreaksRules(reply: string): boolean {
  return PROMISE_IN_TEXT.test(reply) || DATE_IN_TEXT.test(reply);
}
