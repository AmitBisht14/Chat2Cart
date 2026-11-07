import Database from "better-sqlite3";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import pino from "pino";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  STATUS_CONNECTION_LOST,
  STATUS_LOGGED_OUT,
  emitClose,
  fakeBaileys,
  lastFakeSocket,
  resetFakeBaileys,
} from "../fakes/baileys.js";
import { createSchemaDatabase } from "../fakes/database.js";
import type { FakeSocket } from "../fakes/fakeSocket.js";
import { LOGGED_OUT_DETAIL, startConnection } from "../../src/whatsapp/connection.js";
import { HEARTBEAT_INTERVAL_MS } from "../../src/whatsapp/state.js";

vi.mock("@whiskeysockets/baileys", async () => {
  const { createBaileysMock } = await import("../fakes/baileys.js");
  return createBaileysMock();
});

const SESSION_DIR = "/tmp/chat2cart-test-session";
const logger = pino({ level: "silent" });

let folder: string;
let db: Database.Database;

beforeEach(() => {
  vi.useFakeTimers();
  resetFakeBaileys();
  folder = mkdtempSync(path.join(tmpdir(), "chat2cart-connection-"));
  const dbPath = path.join(folder, "chat2cart.sqlite");
  createSchemaDatabase(dbPath, 1);
  db = new Database(dbPath);
});

afterEach(() => {
  db.close();
  rmSync(folder, { recursive: true, force: true });
  vi.useRealTimers();
});

function connectionStarted(onMessage = vi.fn()): { stop: () => void; onMessage: typeof onMessage } {
  const connection = startConnection({ sessionDir: SESSION_DIR, logger, db, onMessage });
  return { ...connection, onMessage };
}

function storedState(): { state: string; detail: string | null } | undefined {
  const row = db.prepare("SELECT state, detail FROM whatsapp_state WHERE id = 1").get();
  return row as { state: string; detail: string | null } | undefined;
}

async function lastSocket(): Promise<FakeSocket> {
  await vi.advanceTimersByTimeAsync(0);
  return lastFakeSocket();
}

it("pins_baileys_to_an_exact_version", () => {
  const manifest = path.resolve(import.meta.dirname, "../../package.json");
  const dependencies = (
    JSON.parse(readFileSync(manifest, "utf8")) as {
      dependencies: Record<string, string>;
    }
  ).dependencies;

  expect(dependencies["@whiskeysockets/baileys"]).toMatch(/^\d+\.\d+\.\d+(-[\w.]+)?$/);
});

it("saves_credentials_whenever_they_update", async () => {
  connectionStarted();
  const socket = await lastSocket();

  socket.ev.emit("creds.update", {});

  expect(fakeBaileys.saveCreds).toHaveBeenCalledTimes(1);
});

it("passes_a_notify_message_to_the_handler", async () => {
  const { onMessage } = connectionStarted();
  const socket = await lastSocket();
  const message = { key: { id: "m1" } };

  socket.ev.emit("messages.upsert", { type: "notify", messages: [message] });
  await vi.advanceTimersByTimeAsync(0);

  expect(onMessage).toHaveBeenCalledWith(message);
});

it("ignores_messages_that_are_not_new_notifications", async () => {
  const { onMessage } = connectionStarted();
  const socket = await lastSocket();

  socket.ev.emit("messages.upsert", { type: "append", messages: [{ key: { id: "m1" } }] });
  await vi.advanceTimersByTimeAsync(0);

  expect(onMessage).not.toHaveBeenCalled();
});

it("keeps_delivering_when_the_handler_throws", async () => {
  const onMessage = vi.fn().mockRejectedValueOnce(new Error("boom"));
  connectionStarted(onMessage);
  const socket = await lastSocket();

  socket.ev.emit("messages.upsert", {
    type: "notify",
    messages: [{ key: { id: "a" } }, { key: { id: "b" } }],
  });
  await vi.advanceTimersByTimeAsync(0);

  expect(onMessage).toHaveBeenCalledTimes(2);
});

it("reconnects_with_the_same_session_folder_after_a_connection_loss", async () => {
  connectionStarted();
  emitClose(await lastSocket(), STATUS_CONNECTION_LOST);

  await vi.advanceTimersByTimeAsync(500);

  expect(fakeBaileys.useMultiFileAuthState.mock.calls).toEqual([[SESSION_DIR], [SESSION_DIR]]);
  expect(fakeBaileys.sockets).toHaveLength(2);
});

it("doubles_the_reconnect_delay_until_the_connection_opens", async () => {
  connectionStarted();
  emitClose(await lastSocket(), STATUS_CONNECTION_LOST);
  await vi.advanceTimersByTimeAsync(500);
  emitClose(await lastSocket(), STATUS_CONNECTION_LOST);

  await vi.advanceTimersByTimeAsync(999);
  expect(fakeBaileys.sockets).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1);

  expect(fakeBaileys.sockets).toHaveLength(3);
});

it("does_not_reconnect_after_a_logout", async () => {
  connectionStarted();
  emitClose(await lastSocket(), STATUS_LOGGED_OUT);

  await vi.advanceTimersByTimeAsync(60_000);

  expect(fakeBaileys.sockets).toHaveLength(1);
});

it("stop_ends_the_socket_and_cancels_a_pending_reconnect", async () => {
  const { stop } = connectionStarted();
  const socket = await lastSocket();
  emitClose(socket, STATUS_CONNECTION_LOST);

  stop();
  await vi.advanceTimersByTimeAsync(60_000);

  expect(socket.end).toHaveBeenCalled();
  expect(fakeBaileys.sockets).toHaveLength(1);
});

it("writes_connected_when_the_connection_opens", async () => {
  connectionStarted();
  const socket = await lastSocket();

  socket.ev.emit("connection.update", { connection: "open" });

  expect(storedState()?.state).toBe("connected");
});

it("writes_reconnecting_with_the_status_code_after_a_connection_loss_and_reconnects", async () => {
  connectionStarted();
  emitClose(await lastSocket(), STATUS_CONNECTION_LOST);

  await vi.advanceTimersByTimeAsync(500);

  expect(storedState()).toEqual({
    state: "reconnecting",
    detail: "connection closed (status 408)",
  });
  expect(fakeBaileys.sockets).toHaveLength(2);
});

it("writes_logged_out_and_never_reconnects_even_after_the_timers_run", async () => {
  connectionStarted();
  emitClose(await lastSocket(), STATUS_LOGGED_OUT);

  await vi.advanceTimersByTimeAsync(24 * 60 * 60 * 1000);

  expect(storedState()).toEqual({ state: "logged_out", detail: LOGGED_OUT_DETAIL });
  expect(fakeBaileys.sockets).toHaveLength(1);
});

it("stops_the_heartbeat_when_the_connection_closes", async () => {
  connectionStarted();
  const socket = await lastSocket();
  socket.ev.emit("connection.update", { connection: "open" });
  emitClose(socket, STATUS_CONNECTION_LOST);
  const heartbeatAtClose = db.prepare("SELECT heartbeat_at FROM whatsapp_state").get();

  await vi.advanceTimersByTimeAsync(HEARTBEAT_INTERVAL_MS * 3);

  expect(db.prepare("SELECT heartbeat_at FROM whatsapp_state").get()).toEqual(heartbeatAtClose);
});
