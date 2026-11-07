import Database from "better-sqlite3";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, it } from "vitest";
import { DatabaseSchemaError, SCHEMA_TOO_OLD_MESSAGE, openDatabase } from "../src/db.js";

const INIT_SQL = path.resolve(
  import.meta.dirname,
  "../../agent/src/chat2cart/db/migrations/001_init.sql",
);

let folder: string;
let dbPath: string;

beforeEach(() => {
  folder = mkdtempSync(path.join(tmpdir(), "chat2cart-db-"));
  dbPath = path.join(folder, "chat2cart.sqlite");
});

afterEach(() => {
  rmSync(folder, { recursive: true, force: true });
});

function createDatabase(version: number): void {
  const db = new Database(dbPath);
  db.exec(readFileSync(INIT_SQL, "utf8"));
  db.prepare("INSERT INTO schema_meta (version) VALUES (?)").run(version);
  db.close();
}

it("opens_a_database_at_the_expected_schema_version", () => {
  createDatabase(1);

  const db = openDatabase(dbPath);

  expect(db.pragma("journal_mode", { simple: true })).toBe("wal");
  db.close();
});

it("refuses_a_database_with_an_older_schema_version", () => {
  createDatabase(0);

  expect(() => openDatabase(dbPath)).toThrow(SCHEMA_TOO_OLD_MESSAGE);
});

it("refuses_a_database_file_that_does_not_exist", () => {
  expect(() => openDatabase(dbPath)).toThrow(DatabaseSchemaError);
});
