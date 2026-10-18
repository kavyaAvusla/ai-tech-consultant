import { loadEmails, selectEmails } from "../dataset.js";
import { loadEnv, redactSecrets, requireEnv } from "../env.js";
import { maskPii } from "../pii.js";
import { isFailure, runEmail } from "../pipeline.js";
import { PROMPT_VERSION } from "../prompts/version.js";
import { openOutputStore, recordOutput } from "../store.js";

function readArgs(argv: string[]): { count: number; ids?: string[] } {
  let count = 8;
  let ids: string[] | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--n") {
      const value = Number(argv[i + 1]);
      if (!Number.isInteger(value) || value < 1) {
        throw new Error("--n expects a positive integer.");
      }
      count = value;
      i += 1;
    } else if (arg === "--ids") {
      ids = (argv[i + 1] || "")
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean);
      i += 1;
    } else if (arg === "--help") {
      console.log("Usage: npm run pipeline -- --n 8");
      console.log("       npm run pipeline -- --ids ht-01,ts-03");
      process.exit(0);
    }
  }
  return { count, ids };
}

function pad(value: string, width: number): string {
  const text = value.replace(/\s+/g, " ");
  return text.length >= width ? text.slice(0, width - 1) + "…" : text.padEnd(width);
}

async function main(): Promise<void> {
  const env = loadEnv();
  requireEnv(env);
  const { count, ids } = readArgs(process.argv.slice(2));
  const emails = selectEmails(loadEmails(), ids ? ids.length : count, ids);
  const store = openOutputStore();

  console.log(`prompt_version=${PROMPT_VERSION}  emails=${emails.length}  model=${env.modelName}`);
  console.log(
    [
      pad("id", 8),
      pad("category", 22),
      pad("evidence", 13),
      pad("risk", 8),
      pad("approval", 10),
      pad("kb", 18),
      pad("inject", 8),
      "next_action",
    ].join(" "),
  );

  let failures = 0;
  for (const email of emails) {
    const row = await runEmail(env, email);
    recordOutput(store, row);
    if (isFailure(row)) {
      failures += 1;
      const message = redactSecrets(row.message, env);
      console.log(
        [
          pad(email.id, 8),
          pad(row.stage, 22),
          pad("—", 13),
          pad("—", 8),
          pad("yes", 10),
          pad("failed", 18),
          pad("—", 8),
          message,
        ].join(" "),
      );
      console.log(`  summary: (no reply drafted)`);
      console.log(`  failure: ${message}`);
      continue;
    }
    console.log(
      [
        pad(row.email_id, 8),
        pad(row.category, 22),
        pad(row.evidence, 13),
        pad(row.risk_level, 8),
        pad(row.needs_human_approval ? "yes" : "no", 10),
        pad(row.kb_status, 18),
        pad(row.prompt_injection_detected ? "yes" : "no", 8),
        row.next_action,
      ].join(" "),
    );
    console.log(`  summary: ${row.request_summary}`);
    console.log(`  sources: ${row.sources.length > 0 ? row.sources.join(" | ") : "(none)"}`);
    if (row.escalation_id) console.log(`  escalation_id: ${row.escalation_id}`);
    if (row.failure_reason) {
      console.log(`  failure: ${maskPii(redactSecrets(row.failure_reason, env))}`);
    } else {
      console.log(`  claims: ${row.unsupported_claims.length}  claim_ok=${row.claim_check_passed}`);
      if (row.email_id === "ts-03" || row.unsupported_claims.length > 0) {
        console.log("  BEFORE claim check:");
        console.log(maskPii(row.draft_before_claim_check));
        console.log("  AFTER claim check:");
        console.log(maskPii(row.suggested_reply));
        for (const claim of row.unsupported_claims) {
          console.log(`  unsupported (${claim.action}): ${maskPii(claim.text)}`);
        }
      } else {
        const preview = maskPii(row.suggested_reply).replace(/\s+/g, " ").slice(0, 280);
        console.log(`  reply: ${preview}`);
      }
    }
  }

  if (failures > 0) {
    process.exitCode = 1;
  }
}

main().catch((error: unknown) => {
  const env = loadEnv();
  const message = error instanceof Error ? error.message : "Pipeline failed.";
  console.error(redactSecrets(message, env));
  process.exitCode = 1;
});
