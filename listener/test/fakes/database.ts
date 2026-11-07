import Database from "better-sqlite3";
import { readFileSync } from "node:fs";
import path from "node:path";

const INIT_SQL = path.resolve(
  import.meta.dirname,
  "../../../agent/src/chat2cart/db/migrations/001_init.sql",
);

// Builds a database file from the agent's real 001_init.sql, at the given schema version.
export function createSchemaDatabase(dbPath: string, version: number): void {
  const db = new Database(dbPath);
  db.exec(readFileSync(INIT_SQL, "utf8"));
  db.prepare("INSERT INTO schema_meta (version) VALUES (?)").run(version);
  db.close();
}
