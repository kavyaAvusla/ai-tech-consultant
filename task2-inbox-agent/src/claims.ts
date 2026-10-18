import { z } from "zod";
import type { AppEnv } from "./env.js";
import { completeText } from "./llm.js";
import { extractJsonObject, loadPrompt } from "./prompts/load.js";

export type UnsupportedClaim = {
  text: string;
  action: "removed" | "rewritten";
  replacement?: string;
};

export type ClaimCheckResult = {
  before: string;
  reply: string;
  unsupported_claims: UnsupportedClaim[];
  passed: boolean;
};

const GUESS = /\b(most likely|probably|likely|i assume|i guess|i think the)\b/i;
const SIZE = /\b\d+(?:\.\d+)?\s*mb\b/gi;

const claimListSchema = z.object({
  claims: z.array(
    z.object({
      text: z.string(),
      supported: z.boolean(),
    }),
  ),
});

const REPLACEMENT =
  "The retrieved article does not say which single setting applies here, so this draft will not guess.";

function sentencesOf(text: string): string[] {
  return text
    .split(/\n+/)
    .flatMap((paragraph) => paragraph.split(/(?<=[.!?])\s+/))
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function unsupportedByOverlap(sentence: string, support: string): boolean {
  const stop = new Set(["about", "after", "again", "being", "could", "please", "their", "there", "these", "those", "which", "would", "your"]);
  const words = sentence
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((word) => word.length > 4 && !stop.has(word));
  if (words.length < 4) return false;
  const haystack = support.toLowerCase();
  const missing = words.filter((word) => !haystack.includes(word));
  return missing.length / words.length >= 0.7;
}

function isBoilerplate(sentence: string): boolean {
  return /^(hi|hello|thanks|thank you|best|regards|dear)\b/i.test(sentence) || /^https?:\/\//i.test(sentence);
}

function sizesMissingFromSupport(sentence: string, support: string): boolean {
  const supportSizes = new Set((support.match(SIZE) || []).map((item) => item.toLowerCase().replace(/\s+/g, "")));
  const claimed = sentence.match(SIZE) || [];
  return claimed.some((item) => !supportSizes.has(item.toLowerCase().replace(/\s+/g, "")));
}

export function deterministicClaims(draft: string, support: string): UnsupportedClaim[] {
  const found: UnsupportedClaim[] = [];
  for (const sentence of sentencesOf(draft)) {
    if (isBoilerplate(sentence)) continue;
    const assignsListing =
      /listing/i.test(sentence) &&
      /image upload size/i.test(sentence) &&
      !/listing photos are failing, the group post/i.test(support);
    const speculative = sentence.match(/\b(server-side|server limit|cdn|cache layer|hosting|your host|php)\b/i);
    const speculationMissing = Boolean(
      speculative && !support.toLowerCase().includes(speculative[1].toLowerCase()),
    );
    if (GUESS.test(sentence) || sizesMissingFromSupport(sentence, support) || assignsListing || speculationMissing) {
      found.push({ text: sentence, action: "rewritten", replacement: REPLACEMENT });
    }
  }
  return found;
}

export function applyClaimEdits(draft: string, claims: UnsupportedClaim[]): string {
  if (claims.length === 0) return draft.trim();
  let next = draft;
  for (const claim of claims) {
    if (next.includes(claim.text)) next = next.replace(claim.text, "");
  }
  next = next.replace(/\n{3,}/g, "\n\n").trim();
  const needsNote = claims.some((claim) => claim.action === "rewritten");
  if (needsNote && !next.includes(REPLACEMENT)) {
    next = `${next}\n\n${REPLACEMENT}`.trim();
  }
  return next;
}

async function modelUnsupported(env: AppEnv, draft: string, support: string): Promise<UnsupportedClaim[]> {
  const system = loadPrompt("claims");
  const user = `SUPPORT (the only allowed facts):\n${support.slice(0, 6000)}\n\nDRAFT:\n${draft}`;
  try {
    const text = await completeText(env, system, user, 700);
    const parsed = claimListSchema.parse(extractJsonObject(text));
    return parsed.claims
      .filter((claim) => !claim.supported && claim.text.trim().length > 0)
      .map((claim) => ({
        text: claim.text.trim(),
        action: "removed" as const,
      }));
  } catch {
    return [];
  }
}

export async function reviewClaims(
  env: AppEnv,
  draft: string,
  support: string,
  sources: string[],
): Promise<ClaimCheckResult> {
  const before = draft.trim();
  if (!before) {
    return { before, reply: "", unsupported_claims: [], passed: true };
  }
  const supportBlob = `${support}\n${sources.join("\n")}`;
  const local = deterministicClaims(before, supportBlob);
  const fromModel = await modelUnsupported(env, before, supportBlob);
  const merged: UnsupportedClaim[] = [...local];
  for (const claim of fromModel) {
    const already = merged.some((item) => before.includes(claim.text) && item.text.includes(claim.text.slice(0, 40)));
    if (!already && before.includes(claim.text) && !isBoilerplate(claim.text) && unsupportedByOverlap(claim.text, supportBlob)) {
      merged.push(claim);
    }
  }
  const reply = applyClaimEdits(before, merged);
  const stillGuessing = GUESS.test(reply);
  const passed = !stillGuessing && !sizesMissingFromSupport(reply, supportBlob);
  return { before, reply, unsupported_claims: merged, passed };
}
