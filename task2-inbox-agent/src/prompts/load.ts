import { readFileSync } from "node:fs";
import path from "node:path";
import { z } from "zod";
import { TASK_ROOT } from "../env.js";
import { PROMPT_VERSION } from "./version.js";

export function loadPrompt(name: "classify" | "draft" | "claims"): string {
  const filePath = path.join(TASK_ROOT, "prompts", PROMPT_VERSION, `${name}.txt`);
  const text = readFileSync(filePath, "utf8").trim();
  if (text.length < 20) {
    throw new Error(`Prompt ${PROMPT_VERSION}/${name} is empty.`);
  }
  return text;
}

export const classifyModelSchema = z.object({
  category: z.enum([
    "how_to",
    "troubleshooting",
    "project_request",
    "refund_cancellation",
    "complaint",
    "quote_request",
    "follow_up",
  ]),
  urgency: z.enum(["low", "normal", "high"]),
  risk_level: z.enum(["low", "medium", "high"]),
  request_summary: z.string().min(1).max(500),
});

export type ClassifyModel = z.infer<typeof classifyModelSchema>;

export function extractJsonObject(text: string): unknown {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const raw = fenced?.[1] ?? trimmed;
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start < 0 || end <= start) {
    throw new Error("Model did not return a JSON object.");
  }
  return JSON.parse(raw.slice(start, end + 1)) as unknown;
}
