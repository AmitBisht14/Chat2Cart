import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { z } from "zod";

export const HEARTBEAT_INTERVAL_MS = 60_000;

const UPSERT_STATE = `
  INSERT INTO whatsapp_state (id, state, changed_at, detail) VALUES (1, ?, ?, ?)
  ON CONFLICT(id) DO UPDATE SET
    state = excluded.state,
    changed_at = CASE WHEN whatsapp_state.state = excluded.state
                      THEN whatsapp_state.changed_at ELSE excluded.changed_at END,
    detail = excluded.detail`;

const stateRow = z.object({ state: z.string() });

export type WhatsAppState = "connected" | "reconnecting" | "logged_out" | "stopped";

export type StateDeps = {
  readonly db: Database.Database;
  readonly logger: Logger;
  readonly clock?: () => Date;
};

export function writeState(deps: StateDeps, state: WhatsAppState, detail?: string): void {
  const previous = readState(deps.db);
  deps.db.prepare(UPSERT_STATE).run(state, isoNow(deps), detail ?? null);
  if (previous === state) return;
  deps.logger.info({ from: previous ?? null, to: state }, "whatsapp_state_changed");
}

export function startHeartbeat(deps: StateDeps): () => void {
  beat(deps);
  const timer = setInterval(() => {
    beat(deps);
  }, HEARTBEAT_INTERVAL_MS);
  // unref: a heartbeat alone must not keep the process alive.
  timer.unref();
  return () => {
    clearInterval(timer);
  };
}

function beat(deps: StateDeps): void {
  try {
    deps.db.prepare("UPDATE whatsapp_state SET heartbeat_at = ? WHERE id = 1").run(isoNow(deps));
  } catch (error) {
    deps.logger.error({ err: error }, "whatsapp_heartbeat_failed");
  }
}

function readState(db: Database.Database): string | undefined {
  const row = db.prepare("SELECT state FROM whatsapp_state WHERE id = 1").get();
  return row === undefined ? undefined : stateRow.parse(row).state;
}

function isoNow(deps: StateDeps): string {
  return (deps.clock ?? (() => new Date()))().toISOString();
}
