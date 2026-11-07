import { readFileSync } from "node:fs";
import path from "node:path";
import pino from "pino";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FakeSocket } from "../fakes/fakeSocket.js";
import { startConnection } from "../../src/whatsapp/connection.js";

const baileys = vi.hoisted(() => ({
  sockets: [] as unknown[],
  saveCreds: vi.fn(),
  useMultiFileAuthState: vi.fn(),
}));

vi.mock("@whiskeysockets/baileys", async () => {
  const { createFakeSocket } = await import("../fakes/fakeSocket.js");
  return {
    default: vi.fn(() => {
      const socket = createFakeSocket();
      baileys.sockets.push(socket);
      return socket;
    }),
    DisconnectReason: { loggedOut: 401, connectionLost: 408 },
    useMultiFileAuthState: baileys.useMultiFileAuthState,
  };
});

const SESSION_DIR = "/tmp/chat2cart-test-session";
const CONNECTION_LOST = 408;
const LOGGED_OUT = 401;
const logger = pino({ level: "silent" });

beforeEach(() => {
  vi.useFakeTimers();
  baileys.sockets.length = 0;
  baileys.saveCreds.mockResolvedValue(undefined);
  baileys.useMultiFileAuthState.mockReset();
  baileys.useMultiFileAuthState.mockResolvedValue({ state: {}, saveCreds: baileys.saveCreds });
});

afterEach(() => {
  vi.useRealTimers();
});

function connectionStarted(onMessage = vi.fn()): { stop: () => void; onMessage: typeof onMessage } {
  const connection = startConnection({ sessionDir: SESSION_DIR, logger, onMessage });
  return { ...connection, onMessage };
}

async function lastSocket(): Promise<FakeSocket> {
  await vi.advanceTimersByTimeAsync(0);
  return baileys.sockets[baileys.sockets.length - 1] as FakeSocket;
}

function closeWith(socket: FakeSocket, statusCode: number): void {
  socket.ev.emit("connection.update", {
    connection: "close",
    lastDisconnect: { error: { output: { statusCode } }, date: new Date() },
  });
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

  expect(baileys.saveCreds).toHaveBeenCalledTimes(1);
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
  closeWith(await lastSocket(), CONNECTION_LOST);

  await vi.advanceTimersByTimeAsync(500);

  expect(baileys.useMultiFileAuthState.mock.calls).toEqual([[SESSION_DIR], [SESSION_DIR]]);
  expect(baileys.sockets).toHaveLength(2);
});

it("doubles_the_reconnect_delay_until_the_connection_opens", async () => {
  connectionStarted();
  closeWith(await lastSocket(), CONNECTION_LOST);
  await vi.advanceTimersByTimeAsync(500);
  closeWith(await lastSocket(), CONNECTION_LOST);

  await vi.advanceTimersByTimeAsync(999);
  expect(baileys.sockets).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1);

  expect(baileys.sockets).toHaveLength(3);
});

it("does_not_reconnect_after_a_logout", async () => {
  connectionStarted();
  closeWith(await lastSocket(), LOGGED_OUT);

  await vi.advanceTimersByTimeAsync(60_000);

  expect(baileys.sockets).toHaveLength(1);
});

it("stop_ends_the_socket_and_cancels_a_pending_reconnect", async () => {
  const { stop } = connectionStarted();
  const socket = await lastSocket();
  closeWith(socket, CONNECTION_LOST);

  stop();
  await vi.advanceTimersByTimeAsync(60_000);

  expect(socket.end).toHaveBeenCalled();
  expect(baileys.sockets).toHaveLength(1);
});
