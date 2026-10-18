import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SRC_DIR = path.dirname(fileURLToPath(import.meta.url));
export const TASK_ROOT = path.resolve(SRC_DIR, "..");

export type AppEnv = {
  kbApiUrl: string;
  kbApiKey: string;
  anthropicApiKey: string;
  modelName: string;
};

function parseEnvFile(filePath: string): Record<string, string> {
  let text = "";
  try {
    text = readFileSync(filePath, "utf8");
  } catch {
    return {};
  }
  const out: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 1) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

export function loadEnv(): AppEnv {
  const local = parseEnvFile(path.join(TASK_ROOT, ".env"));
  // Standalone runs should set the two secrets in this folder's .env.
  // If they are still blank, use the repo-root .env in memory (Task 1's keys).
  const root = parseEnvFile(path.join(TASK_ROOT, "..", ".env"));
  const kbApiUrl = (local.KB_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const kbApiKey = local.KB_API_KEY || root.APP_API_KEY || "";
  const anthropicApiKey = local.ANTHROPIC_API_KEY || root.ANTHROPIC_API_KEY || "";
  const modelName = local.MODEL_NAME || root.MODEL_NAME || "claude-haiku-5-5";
  return { kbApiUrl, kbApiKey, anthropicApiKey, modelName };
}

export function redactSecrets(text: string, env: AppEnv): string {
  let out = text;
  for (const secret of [env.kbApiKey, env.anthropicApiKey]) {
    if (secret && secret.length > 0) {
      out = out.split(secret).join("[redacted]");
    }
  }
  return out;
}

export function requireEnv(env: AppEnv): void {
  const missing: string[] = [];
  if (!env.kbApiKey) missing.push("KB_API_KEY");
  if (!env.anthropicApiKey) missing.push("ANTHROPIC_API_KEY");
  if (missing.length > 0) {
    throw new Error(
      `Missing ${missing.join(" and ")} in task2-inbox-agent/.env. Copy them by hand. See .env.example.`,
    );
  }
}
