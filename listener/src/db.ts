import Database from "better-sqlite3";
import { z } from "zod";

export const EXPECTED_SCHEMA_VERSION = 1;
export const SCHEMA_TOO_OLD_MESSAGE =
  "Database schema is older than required. Start the agent once to run migrations.";

const BUSY_TIMEOUT_MS = 5000;

const schemaMetaRow = z.object({ version: z.number().int() });

export class DatabaseSchemaError extends Error {}

export function openDatabase(dbPath: string): Database.Database {
  const db = openExistingFile(dbPath);
  db.pragma("journal_mode = WAL");
  db.pragma(`busy_timeout = ${BUSY_TIMEOUT_MS}`);
  if (readSchemaVersion(db) < EXPECTED_SCHEMA_VERSION) {
    db.close();
    throw new DatabaseSchemaError(SCHEMA_TOO_OLD_MESSAGE);
  }
  return db;
}

function openExistingFile(dbPath: string): Database.Database {
  try {
    return new Database(dbPath, { fileMustExist: true });
  } catch (error) {
    throw new DatabaseSchemaError(SCHEMA_TOO_OLD_MESSAGE, { cause: error });
  }
}

function readSchemaVersion(db: Database.Database): number {
  const hasTable = db
    .prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'")
    .get();
  if (hasTable === undefined) return 0;
  const row = db.prepare("SELECT version FROM schema_meta").get();
  return row === undefined ? 0 : schemaMetaRow.parse(row).version;
}
