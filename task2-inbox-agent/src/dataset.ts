import { readFileSync } from "node:fs";
import path from "node:path";
import { TASK_ROOT } from "./env.js";
import {
  EXPECTED_COUNTS,
  emailSchema,
  type Category,
  type SupportEmail,
} from "./schema.js";

export function loadEmails(): SupportEmail[] {
  const filePath = path.join(TASK_ROOT, "emails", "emails.json");
  const parsed: unknown = JSON.parse(readFileSync(filePath, "utf8"));
  if (!Array.isArray(parsed)) {
    throw new Error("emails/emails.json must be an array.");
  }
  const emails = parsed.map((row, index) => {
    const result = emailSchema.safeParse(row);
    if (!result.success) {
      throw new Error(`Email at index ${index} is invalid: ${result.error.message}`);
    }
    return result.data;
  });
  assertDataset(emails);
  return emails;
}

export function assertDataset(emails: SupportEmail[]): void {
  if (emails.length !== 50) {
    throw new Error(`Expected 50 emails, found ${emails.length}.`);
  }
  const ids = new Set<string>();
  const counts: Record<Category, number> = {
    how_to: 0,
    troubleshooting: 0,
    project_request: 0,
    refund_cancellation: 0,
    complaint: 0,
    quote_request: 0,
    follow_up: 0,
  };
  let heldOut = 0;
  let uncoveredProduct = 0;
  for (const email of emails) {
    if (ids.has(email.id)) throw new Error(`Duplicate email id ${email.id}.`);
    ids.add(email.id);
    counts[email.expected_category] += 1;
    if (email.held_out) heldOut += 1;
    const product =
      email.expected_category === "how_to" || email.expected_category === "troubleshooting";
    if (product && email.expected_source_url === "escalate") uncoveredProduct += 1;
  }
  for (const [category, expected] of Object.entries(EXPECTED_COUNTS)) {
    const actual = counts[category as Category];
    if (actual !== expected) {
      throw new Error(`Expected ${expected} ${category} emails, found ${actual}.`);
    }
  }
  if (heldOut !== 10) throw new Error(`Expected 10 held_out emails, found ${heldOut}.`);
  if (uncoveredProduct < 8) {
    throw new Error(`Expected at least 8 uncovered how-to/troubleshooting emails, found ${uncoveredProduct}.`);
  }
}

/** Stable mix: every category, one uncovered how-to, and the prompt-injection email. */
export const SAMPLE_IDS = [
  "ht-08",
  "ht-10",
  "ts-03",
  "pr-01",
  "rf-01",
  "cp-01",
  "qu-01",
  "fu-01",
] as const;

export function selectEmails(emails: SupportEmail[], count: number, ids?: string[]): SupportEmail[] {
  if (count < 1) throw new Error("--n must be at least 1.");
  const byId = new Map(emails.map((email) => [email.id, email]));
  if (ids && ids.length > 0) {
    return ids.map((id) => {
      const email = byId.get(id);
      if (!email) throw new Error(`Unknown email id ${id}.`);
      return email;
    });
  }
  const chosen: SupportEmail[] = [];
  const seen = new Set<string>();
  for (const id of SAMPLE_IDS) {
    if (chosen.length >= count) break;
    const email = byId.get(id);
    if (!email || email.held_out) continue;
    chosen.push(email);
    seen.add(email.id);
  }
  const rest = emails
    .filter((email) => !email.held_out && !seen.has(email.id))
    .slice()
    .sort((a, b) => a.id.localeCompare(b.id));
  for (const email of rest) {
    if (chosen.length >= count) break;
    chosen.push(email);
  }
  if (chosen.length < count) {
    throw new Error(`Only ${chosen.length} emails available for a run of ${count}.`);
  }
  return chosen;
}
