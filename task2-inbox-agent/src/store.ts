import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { TASK_ROOT } from "./env.js";
import type { Category, PipelineOutput } from "./schema.js";
import { categorySchema } from "./schema.js";

const globalStore = globalThis as { __inboxDb?: DatabaseSync };

export type CategoryStat = {
  category: Category;
  consecutive_identical: number;
  eligible: boolean;
  trial_enabled: boolean;
  never_eligible: boolean;
};

export type FeedbackRow = {
  id: number;
  version: number;
  email_id: string;
  original_email: string;
  predicted_category: string;
  sources_json: string;
  generated_draft: string;
  human_edited_reply: string | null;
  final_sent_reply: string | null;
  model_name: string;
  prompt_version: string;
  approval_outcome: string;
  reason: string | null;
  claim_check_passed: number;
  quality_check_passed: number;
  created_at: string;
};

export type SentRow = {
  id: number;
  idempotency_key: string;
  email_id: string;
  category: string;
  body: string;
  created_at: string;
};

export function openOutputStore(): DatabaseSync {
  if (globalStore.__inboxDb) return globalStore.__inboxDb;
  const dir = path.join(TASK_ROOT, "data");
  mkdirSync(dir, { recursive: true });
  const db = new DatabaseSync(path.join(dir, "pipeline.sqlite"));
  db.exec(`
    CREATE TABLE IF NOT EXISTS pipeline_outputs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email_id TEXT NOT NULL,
      prompt_version TEXT NOT NULL,
      created_at TEXT NOT NULL,
      output_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS drafts (
      email_id TEXT PRIMARY KEY,
      prompt_version TEXT NOT NULL,
      model_name TEXT NOT NULL,
      output_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      version INTEGER NOT NULL,
      email_id TEXT NOT NULL,
      original_email TEXT NOT NULL,
      predicted_category TEXT NOT NULL,
      sources_json TEXT NOT NULL,
      generated_draft TEXT NOT NULL,
      human_edited_reply TEXT,
      final_sent_reply TEXT,
      model_name TEXT NOT NULL,
      prompt_version TEXT NOT NULL,
      approval_outcome TEXT NOT NULL,
      reason TEXT,
      claim_check_passed INTEGER NOT NULL,
      quality_check_passed INTEGER NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sent (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      idempotency_key TEXT NOT NULL UNIQUE,
      email_id TEXT NOT NULL,
      category TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS category_stats (
      category TEXT PRIMARY KEY,
      consecutive_identical INTEGER NOT NULL DEFAULT 0,
      eligible INTEGER NOT NULL DEFAULT 0,
      trial_enabled INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    );
  `);
  globalStore.__inboxDb = db;
  return db;
}

export function recordOutput(
  db: DatabaseSync,
  output: PipelineOutput | { email_id: string; prompt_version: string },
): void {
  const statement = db.prepare(
    `INSERT INTO pipeline_outputs (email_id, prompt_version, created_at, output_json)
     VALUES (?, ?, ?, ?)`,
  );
  statement.run(output.email_id, output.prompt_version, new Date().toISOString(), JSON.stringify(output));
}

export function saveDraft(db: DatabaseSync, output: PipelineOutput): void {
  const statement = db.prepare(
    `INSERT INTO drafts (email_id, prompt_version, model_name, output_json, created_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(email_id) DO UPDATE SET
       prompt_version = excluded.prompt_version,
       model_name = excluded.model_name,
       output_json = excluded.output_json,
       created_at = excluded.created_at`,
  );
  statement.run(
    output.email_id,
    output.prompt_version,
    output.model_name,
    JSON.stringify(output),
    new Date().toISOString(),
  );
}

export function loadDraft(db: DatabaseSync, emailId: string): PipelineOutput | null {
  const row = db.prepare("SELECT output_json FROM drafts WHERE email_id = ?").get(emailId) as
    | { output_json: string }
    | undefined;
  if (!row) return null;
  return JSON.parse(row.output_json) as PipelineOutput;
}

export function nextFeedbackVersion(db: DatabaseSync, emailId: string): number {
  const row = db.prepare("SELECT COALESCE(MAX(version), 0) AS v FROM feedback WHERE email_id = ?").get(emailId) as {
    v: number;
  };
  return Number(row.v) + 1;
}

export function insertFeedback(db: DatabaseSync, row: Omit<FeedbackRow, "id">): number {
  const result = db
    .prepare(
      `INSERT INTO feedback (
        version, email_id, original_email, predicted_category, sources_json, generated_draft,
        human_edited_reply, final_sent_reply, model_name, prompt_version, approval_outcome,
        reason, claim_check_passed, quality_check_passed, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      row.version,
      row.email_id,
      row.original_email,
      row.predicted_category,
      row.sources_json,
      row.generated_draft,
      row.human_edited_reply,
      row.final_sent_reply,
      row.model_name,
      row.prompt_version,
      row.approval_outcome,
      row.reason,
      row.claim_check_passed,
      row.quality_check_passed,
      row.created_at,
    );
  return Number(result.lastInsertRowid);
}

export function findSent(db: DatabaseSync, key: string): SentRow | null {
  const row = db.prepare("SELECT * FROM sent WHERE idempotency_key = ?").get(key) as SentRow | undefined;
  return row ?? null;
}

export function insertSent(db: DatabaseSync, row: Omit<SentRow, "id">): SentRow {
  const existing = findSent(db, row.idempotency_key);
  if (existing) return existing;
  try {
    const result = db
      .prepare(
        `INSERT INTO sent (idempotency_key, email_id, category, body, created_at)
         VALUES (?, ?, ?, ?, ?)`,
      )
      .run(row.idempotency_key, row.email_id, row.category, row.body, row.created_at);
    return {
      id: Number(result.lastInsertRowid),
      ...row,
    };
  } catch (error) {
    const again = findSent(db, row.idempotency_key);
    if (again) return again;
    throw error;
  }
}

export function listSent(db: DatabaseSync): SentRow[] {
  return db.prepare("SELECT * FROM sent ORDER BY id DESC").all() as SentRow[];
}

const ALL_CATEGORIES = categorySchema.options;

export function listCategoryStats(db: DatabaseSync, neverEligible: (category: Category) => boolean): CategoryStat[] {
  const rows = db.prepare("SELECT * FROM category_stats").all() as Array<{
    category: string;
    consecutive_identical: number;
    eligible: number;
    trial_enabled: number;
  }>;
  const byName = new Map(rows.map((row) => [row.category, row]));
  return ALL_CATEGORIES.map((category) => {
    const row = byName.get(category);
    const blocked = neverEligible(category);
    return {
      category,
      consecutive_identical: row?.consecutive_identical ?? 0,
      eligible: !blocked && (row?.eligible ?? 0) === 1,
      trial_enabled: !blocked && (row?.trial_enabled ?? 0) === 1,
      never_eligible: blocked,
    };
  });
}

export function writeCategoryStat(
  db: DatabaseSync,
  stat: { category: Category; consecutive_identical: number; eligible: boolean; trial_enabled: boolean },
): void {
  db.prepare(
    `INSERT INTO category_stats (category, consecutive_identical, eligible, trial_enabled, updated_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(category) DO UPDATE SET
       consecutive_identical = excluded.consecutive_identical,
       eligible = excluded.eligible,
       trial_enabled = excluded.trial_enabled,
       updated_at = excluded.updated_at`,
  ).run(
    stat.category,
    stat.consecutive_identical,
    stat.eligible ? 1 : 0,
    stat.trial_enabled ? 1 : 0,
    new Date().toISOString(),
  );
}
