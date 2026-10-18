import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { HAIKU_IDS, SONNET_IDS } from "./cases.js";
import { tokenCostUsd } from "./prices.js";
import { scoreCase, type ScoreRow } from "./score.js";
import { loadEnv, requireEnv, TASK_ROOT, type AppEnv } from "../src/env.js";
import { readTokenUsage, resetTokenUsage } from "../src/llm.js";
import { isFailure, runEmail } from "../src/pipeline.js";
import { loadEmails } from "../src/dataset.js";
import type { SupportEmail } from "../src/schema.js";

const FIELDS = [
  "task",
  "case_id",
  "model",
  "expected",
  "actual",
  "quality",
  "latency_ms",
  "cost",
  "passed",
  "failure_reason",
] as const;

function csvCell(value: string | number): string {
  const text = String(value);
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function writeCsv(filePath: string, rows: ScoreRow[]): void {
  const lines = [FIELDS.join(",")];
  for (const row of rows) {
    lines.push(FIELDS.map((field) => csvCell(row[field])).join(","));
  }
  writeFileSync(filePath, `${lines.join("\n")}\n`, "utf8");
}

function parseArgs(argv: string[]): { prompt: string; out: string; ids?: Set<string>; append: boolean; noCache: boolean } {
  let prompt = "v1";
  let out = "";
  let ids: Set<string> | undefined;
  let append = false;
  let noCache = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--prompt") prompt = argv[i + 1] || prompt;
    if (argv[i] === "--out") out = argv[i + 1] || out;
    if (argv[i] === "--ids") {
      ids = new Set(
        (argv[i + 1] || "")
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item.length > 0),
      );
    }
    if (argv[i] === "--append") append = true;
    if (argv[i] === "--no-cache") noCache = true;
  }
  if (!/^v\d+$/.test(prompt)) throw new Error("--prompt must look like v1");
  if (!out) out = prompt === "v1" ? "results.csv" : `results_${prompt}.csv`;
  return { prompt, out: path.resolve(TASK_ROOT, "evaluation", out), ids, append, noCache };
}

function cachePath(prompt: string, model: string, id: string): string {
  return path.join(TASK_ROOT, "data", "eval-cache", prompt, model, `${id}.json`);
}

async function runOne(
  env: AppEnv,
  email: SupportEmail,
  prompt: string,
  noCache: boolean,
): Promise<{ latencyMs: number; cost: string; rows: ScoreRow[] }> {
  const file = cachePath(prompt, env.modelName, noCache ? `${email.id}.rerun` : email.id);
  if (!noCache && existsSync(file)) {
    const saved = JSON.parse(readFileSync(file, "utf8")) as {
      latencyMs: number;
      cost: string;
      rows: ScoreRow[];
    };
    console.log(`${email.id} ${env.modelName} cached`);
    return saved;
  }
  resetTokenUsage();
  const started = Date.now();
  const result = await runEmail(env, email, { promptVersion: prompt });
  const latencyMs = Date.now() - started;
  const usage = readTokenUsage();
  const cost = tokenCostUsd(env.modelName, usage.inputTokens, usage.outputTokens).toFixed(6);
  const rows = scoreCase(email, env.modelName, result, latencyMs, cost);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(
    file,
    JSON.stringify(
      {
        latencyMs,
        cost,
        inputTokens: usage.inputTokens,
        outputTokens: usage.outputTokens,
        held_out: email.held_out,
        result,
        rows,
      },
      null,
      2,
    ),
    "utf8",
  );
  const failed = rows.filter((row) => row.passed === "false").map((row) => row.task);
  const label = isFailure(result) ? `FAIL ${result.stage}` : result.category;
  console.log(`${email.id} ${env.modelName} ${label} ${latencyMs}ms $${cost} failed=${failed.join("|") || "none"}`);
  return { latencyMs, cost, rows };
}

function appendCsv(filePath: string, rows: ScoreRow[]): void {
  const lines = rows.map((row) => FIELDS.map((field) => csvCell(row[field])).join(","));
  const previous = existsSync(filePath) ? readFileSync(filePath, "utf8") : `${FIELDS.join(",")}\n`;
  const body = previous.endsWith("\n") ? previous : `${previous}\n`;
  writeFileSync(filePath, `${body}${lines.join("\n")}\n`, "utf8");
}

async function main(): Promise<void> {
  const { prompt, out, ids, append, noCache } = parseArgs(process.argv.slice(2));
  const env = loadEnv();
  requireEnv(env);
  const emails = loadEmails();
  const byId = new Map(emails.map((email) => [email.id, email]));
  const plan: Array<{ model: string; ids: readonly string[] }> = [
    { model: "claude-haiku-5-5", ids: HAIKU_IDS },
    { model: "claude-sonnet-5-5", ids: SONNET_IDS },
  ];
  const all: ScoreRow[] = [];
  for (const item of plan) {
    const modelEnv = { ...env, modelName: item.model };
    const selected = ids ? item.ids.filter((id) => ids.has(id)) : item.ids;
    for (const id of selected) {
      const email = byId.get(id);
      if (!email) throw new Error(`Missing email ${id}`);
      const done = await runOne(modelEnv, email, prompt, noCache);
      all.push(...done.rows);
      if (!append) writeCsv(out, all);
    }
  }
  if (append) appendCsv(out, all);
  console.log(`Wrote ${out} rows=${all.length} append=${append}`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "evaluation failed";
  console.error(message);
  process.exit(1);
});
