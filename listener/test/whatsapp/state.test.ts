import Database from "better-sqlite3";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import pino from "pino";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createSchemaDatabase } from "../fakes/database.js";
import { HEARTBEAT_INTERVAL_MS, startHeartbeat, writeState } from "../../src/whatsapp/state.js";

const logger = pino({ level: "silent" });
const START = new Date("2026-11-07T10:00:00.000Z");

let folder: string;
let db: Database.Database;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(START);
  folder = mkdtempSync(path.join(tmpdir(), "chat2cart-state-"));
  const dbPath = path.join(folder, "chat2cart.sqlite");
  createSchemaDatabase(dbPath, 1);
  db = new Database(dbPath);
});

afterEach(() => {
  db.close();
  rmSync(folder, { recursive: true, force: true });
  vi.useRealTimers();
});

function storedRow(): { state: string; changed_at: string; heartbeat_at: string | null } {
  const row = db.prepare("SELECT state, changed_at, heartbeat_at FROM whatsapp_state").get();
  return row as { state: string; changed_at: string; heartbeat_at: string | null };
}

it("keeps_changed_at_when_the_same_state_is_written_twice", () => {
  writeState({ db, logger }, "connected");
  vi.setSystemTime(new Date(START.getTime() + 5000));

  writeState({ db, logger }, "connected");

  expect(storedRow().changed_at).toBe(START.toISOString());
});

it("updates_changed_at_when_the_state_changes", () => {
  writeState({ db, logger }, "connected");
  const later = new Date(START.getTime() + 5000);
  vi.setSystemTime(later);

  writeState({ db, logger }, "reconnecting", "status 408");

  expect(storedRow()).toMatchObject({ state: "reconnecting", changed_at: later.toISOString() });
});

it("keeps_a_single_row_however_often_the_state_changes", () => {
  writeState({ db, logger }, "connected");
  writeState({ db, logger }, "logged_out");

  const count = db.prepare("SELECT COUNT(*) AS n FROM whatsapp_state").get();

  expect(count).toEqual({ n: 1 });
});

it("advances_heartbeat_at_every_interval_while_the_heartbeat_runs", async () => {
  writeState({ db, logger }, "connected");
  startHeartbeat({ db, logger });
  expect(storedRow().heartbeat_at).toBe(START.toISOString());

  await vi.advanceTimersByTimeAsync(HEARTBEAT_INTERVAL_MS);

  expect(storedRow().heartbeat_at).toBe(
    new Date(START.getTime() + HEARTBEAT_INTERVAL_MS).toISOString(),
  );
});

it("stops_advancing_heartbeat_at_after_the_heartbeat_is_stopped", async () => {
  writeState({ db, logger }, "connected");
  const stopHeartbeat = startHeartbeat({ db, logger });
  stopHeartbeat();

  await vi.advanceTimersByTimeAsync(HEARTBEAT_INTERVAL_MS * 3);

  expect(storedRow().heartbeat_at).toBe(START.toISOString());
});
