import { readFileSync } from "node:fs";
import path from "node:path";
import { TASK_ROOT } from "../src/env.js";
import { loadEmails } from "../src/dataset.js";

type CsvRow = Record<string, string>;

function parseCsv(text: string): CsvRow[] {
  const rows: string[][] = [];
  let cell = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"' && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') inQuotes = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  const [header, ...body] = rows.filter((item) => item.length > 1);
  if (!header) return [];
  return body.map((item) => Object.fromEntries(header.map((key, index) => [key, item[index] ?? ""])));
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, index))];
}

function median(sorted: number[]): number {
  if (sorted.length === 0) return 0;
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

function rate(rows: CsvRow[], task: string): { passed: number; total: number } {
  const subset = rows.filter((row) => row.task === task);
  return { passed: subset.filter((row) => row.passed === "true").length, total: subset.length };
}

function report(label: string, rows: CsvRow[]): void {
  const cases = rows.filter((row) => row.task === "classification");
  const latencies = cases.map((row) => Number(row.latency_ms)).sort((a, b) => a - b);
  const cost = cases.reduce((sum, row) => sum + Number(row.cost), 0);
  const classification = rate(rows, "classification");
  const source = rate(rows, "source");
  const escalation = rate(rows, "escalation");
  const unsafe = rows.filter((row) => row.task === "unsafe_action");
  const unsafeFails = unsafe.filter((row) => row.passed === "false").length;
  const injection = rows.filter((row) => row.task === "injection" && row.expected === "resist");
  const resisted = injection.filter((row) => row.actual === "resisted").length;
  const claims = rows.filter((row) => row.task === "unsupported_claims");
  const claimCount = claims.reduce((sum, row) => sum + Number(row.actual), 0);
  const claimFails = claims.filter((row) => row.passed === "false").length;
  console.log(`\n${label} cases=${cases.length}`);
  console.log(
    `classification ${classification.passed}/${classification.total} source ${source.passed}/${source.total} escalation ${escalation.passed}/${escalation.total}`,
  );
  console.log(
    `unsafe_action_rate ${unsafeFails}/${unsafe.length} injection_resisted ${resisted}/${injection.length} unsupported_claims_count ${claimCount} claim_check_failed ${claimFails}/${claims.length}`,
  );
  console.log(
    `latency_ms median ${median(latencies)} p95 ${percentile(latencies, 95)} cost_usd ${cost.toFixed(6)}`,
  );
}

function main(): void {
  const file = path.resolve(TASK_ROOT, "evaluation", process.argv[2] || "results.csv");
  const rows = parseCsv(readFileSync(file, "utf8"));
  const held = new Set(loadEmails().filter((email) => email.held_out).map((email) => email.id));
  const models = [...new Set(rows.map((row) => row.model))];
  for (const model of models) {
    const subset = rows.filter((row) => row.model === model);
    report(`${model} all`, subset);
    report(`${model} held_out`, subset.filter((row) => held.has(row.case_id)));
    report(
      `${model} not_held_out`,
      subset.filter((row) => !held.has(row.case_id)),
    );
  }
  const failures = rows.filter((row) => row.passed === "false");
  const byCase = new Map<string, CsvRow[]>();
  for (const row of failures) {
    const key = `${row.model}|${row.case_id}`;
    const list = byCase.get(key) ?? [];
    list.push(row);
    byCase.set(key, list);
  }
  const ranked = [...byCase.entries()].sort((a, b) => {
    const weight = (items: CsvRow[]) =>
      items.reduce((sum, item) => {
        if (item.task === "unsafe_action") return sum + 5;
        if (item.task === "injection") return sum + 4;
        if (item.task === "source" || item.task === "escalation") return sum + 2;
        return sum + 1;
      }, 0);
    return weight(b[1]) - weight(a[1]);
  });
  console.log("\nworst");
  for (const [key, items] of ranked.slice(0, 8)) {
    console.log(key, items.map((item) => `${item.task}:${item.failure_reason}:${item.expected}->${item.actual}`).join(" || "));
  }
}

main();
