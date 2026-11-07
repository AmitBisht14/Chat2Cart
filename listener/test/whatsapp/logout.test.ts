import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import pino from "pino";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FakeSocket } from "../fakes/fakeSocket.js";
import { fakeBaileys, lastFakeSocket, resetFakeBaileys } from "../fakes/baileys.js";
import {
  CONFIRM_QUESTION,
  LOGGED_OUT_MESSAGE,
  NO_SESSION_MESSAGE,
  SESSION_REMOVED_ONLY_MESSAGE,
  logoutDevice,
} from "../../src/whatsapp/logout.js";
import type { LogoutResult } from "../../src/whatsapp/logout.js";

vi.mock("@whiskeysockets/baileys", async () => {
  const { createBaileysMock } = await import("../fakes/baileys.js");
  return createBaileysMock();
});

const logger = pino({ level: "silent" });
const SMALL_TIMEOUT_MS = 20;

let sessionDir: string;
let printed: string[];
let recordLoggedOut: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetFakeBaileys();
  sessionDir = mkdtempSync(path.join(tmpdir(), "chat2cart-logout-"));
  writeFileSync(path.join(sessionDir, "creds.json"), JSON.stringify({ registered: true }));
  printed = [];
  recordLoggedOut = vi.fn();
});

afterEach(() => {
  rmSync(sessionDir, { recursive: true, force: true });
});

function run(answer: string, timeoutMs?: number): Promise<LogoutResult> {
  return logoutDevice({
    sessionDir,
    logger,
    io: { ask: vi.fn(() => Promise.resolve(answer)), print: (line) => printed.push(line) },
    recordLoggedOut,
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  });
}

function openWhenCreated(prepare?: (socket: FakeSocket) => void): void {
  void vi
    .waitFor(() => expect(fakeBaileys.sockets.length).toBeGreaterThan(0))
    .then(() => {
      const socket = lastFakeSocket();
      prepare?.(socket);
      socket.ev.emit("connection.update", { connection: "open" });
    });
}

it("logs_out_and_deletes_the_session_when_confirmed", async () => {
  openWhenCreated();

  const result = await run("y");

  expect(result).toBe("logged_out");
  expect(lastFakeSocket().logout).toHaveBeenCalledOnce();
  expect(existsSync(sessionDir)).toBe(false);
  expect(recordLoggedOut).toHaveBeenCalledOnce();
  expect(printed).toEqual([LOGGED_OUT_MESSAGE]);
});

it("asks_before_acting", async () => {
  const ask = vi.fn(() => Promise.resolve("n"));

  await logoutDevice({
    sessionDir,
    logger,
    io: { ask, print: vi.fn() },
    recordLoggedOut,
  });

  expect(ask).toHaveBeenCalledWith(CONFIRM_QUESTION);
});

it.each(["n", "", "maybe"])("keeps_the_session_when_the_answer_is_%j", async (answer) => {
  const result = await run(answer);

  expect(result).toBe("cancelled");
  expect(fakeBaileys.sockets).toHaveLength(0);
  expect(existsSync(sessionDir)).toBe(true);
  expect(recordLoggedOut).not.toHaveBeenCalled();
});

it("reports_no_session_when_the_device_was_never_linked", async () => {
  rmSync(sessionDir, { recursive: true, force: true });

  const result = await run("y");

  expect(result).toBe("no_session");
  expect(printed).toEqual([NO_SESSION_MESSAGE]);
});

it("deletes_the_session_and_points_to_the_phone_when_whatsapp_cannot_be_reached", async () => {
  const result = await run("y", SMALL_TIMEOUT_MS);

  expect(result).toBe("session_removed_only");
  expect(existsSync(sessionDir)).toBe(false);
  expect(recordLoggedOut).toHaveBeenCalledOnce();
  expect(printed).toEqual([SESSION_REMOVED_ONLY_MESSAGE]);
});

it("deletes_the_session_when_the_logout_call_fails", async () => {
  openWhenCreated((socket) => socket.logout.mockRejectedValue(new Error("rejected")));

  const result = await run("y");

  expect(result).toBe("session_removed_only");
  expect(existsSync(sessionDir)).toBe(false);
});
