import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { TASK_ROOT } from "./env.js";
import type { PipelineOutput } from "./schema.js";

export function openOutputStore(): DatabaseSync {
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
    )
  `);
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
  statement.run(
    output.email_id,
    output.prompt_version,
    new Date().toISOString(),
    JSON.stringify(output),
  );
}
