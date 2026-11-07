import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import pino from "pino";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  STATUS_CONNECTION_LOST,
  STATUS_RESTART_REQUIRED,
  emitClose,
  fakeBaileys,
  lastFakeSocket,
  resetFakeBaileys,
} from "../fakes/baileys.js";
import { FAKE_PAIRING_CODE } from "../fakes/fakeSocket.js";
import type { FakeSocket } from "../fakes/fakeSocket.js";
import {
  ALREADY_LINKED_MESSAGE,
  PAIRING_STEPS,
  QR_STEPS,
  login,
} from "../../src/whatsapp/login.js";
import type { LoginResult } from "../../src/whatsapp/login.js";

vi.mock("@whiskeysockets/baileys", async () => {
  const { createBaileysMock } = await import("../fakes/baileys.js");
  return createBaileysMock();
});

const PHONE = "919876543210";
const logger = pino({ level: "silent" });

let sessionDir: string;

beforeEach(() => {
  resetFakeBaileys();
  sessionDir = mkdtempSync(path.join(tmpdir(), "chat2cart-login-"));
});

afterEach(() => {
  rmSync(sessionDir, { recursive: true, force: true });
});

function terminal(answers: string[]): {
  printed: string[];
  io: Parameters<typeof login>[0]["io"];
} {
  const printed: string[] = [];
  const io = {
    ask: vi.fn(() => Promise.resolve(answers.shift() ?? "")),
    print: (line: string) => printed.push(line),
    renderQr: (qr: string) => `QR[${qr}]`,
  };
  return { printed, io };
}

async function startedSocket(): Promise<FakeSocket> {
  await vi.waitFor(() => expect(fakeBaileys.sockets.length).toBeGreaterThan(0));
  return lastFakeSocket();
}

function emitUpdate(socket: FakeSocket, update: Record<string, unknown>): void {
  socket.ev.emit("connection.update", update);
}

it("reports_an_existing_registered_session_and_creates_no_socket", async () => {
  writeFileSync(path.join(sessionDir, "creds.json"), JSON.stringify({ registered: true }));
  const { io, printed } = terminal([]);

  const result = await login({ sessionDir, logger, io });

  expect([result, printed, fakeBaileys.sockets]).toEqual([
    "already_linked",
    [ALREADY_LINKED_MESSAGE],
    [],
  ]);
});

it("treats_an_unregistered_creds_file_as_no_session", async () => {
  writeFileSync(path.join(sessionDir, "creds.json"), JSON.stringify({ registered: false }));
  const { io } = terminal(["1"]);

  const pending = login({ sessionDir, logger, io });
  const socket = await startedSocket();
  emitUpdate(socket, { connection: "open" });

  expect(await pending).toBe("linked");
});

it("prints_the_qr_code_and_the_steps_in_qr_mode", async () => {
  const { io, printed } = terminal(["1"]);

  const pending = login({ sessionDir, logger, io });
  const socket = await startedSocket();
  emitUpdate(socket, { qr: "QRDATA" });
  emitUpdate(socket, { connection: "open" });
  await pending;

  expect(printed.slice(0, 2)).toEqual([QR_STEPS, "QR[QRDATA]"]);
});

it("requests_one_pairing_code_for_digits_only_and_prints_it_with_the_steps", async () => {
  const { io, printed } = terminal(["2", "abc", PHONE]);

  const pending = login({ sessionDir, logger, io });
  const socket = await startedSocket();
  emitUpdate(socket, { qr: "FIRST" });
  emitUpdate(socket, { qr: "SECOND" });
  await vi.waitFor(() => expect(printed).toContain(PAIRING_STEPS));
  emitUpdate(socket, { connection: "open" });
  await pending;

  expect(socket.requestPairingCode.mock.calls).toEqual([[PHONE]]);
  expect(printed).toContain(`Pairing code: ${FAKE_PAIRING_CODE}`);
});

it("saves_credentials_reconnects_after_restart_required_and_links", async () => {
  const { io, printed } = terminal(["1"]);

  const pending = login({ sessionDir, logger, io });
  const first = await startedSocket();
  first.ev.emit("creds.update", {});
  emitClose(first, STATUS_RESTART_REQUIRED);
  await vi.waitFor(() => expect(fakeBaileys.sockets).toHaveLength(2));
  emitUpdate(lastFakeSocket(), { connection: "open" });
  const result = await pending;

  expect(result).toBe("linked");
  expect(fakeBaileys.saveCreds).toHaveBeenCalledTimes(1);
  expect(printed).toContain("Linked. Session saved.");
  expect(lastFakeSocket().end).toHaveBeenCalled();
});

it("fails_when_the_connection_closes_for_any_other_reason", async () => {
  const { io } = terminal(["1"]);

  const pending = login({ sessionDir, logger, io });
  emitClose(await startedSocket(), STATUS_CONNECTION_LOST);

  expect(await pending).toBe<LoginResult>("failed");
});

it("fails_when_nothing_is_linked_within_the_time_limit", async () => {
  const { io, printed } = terminal(["1"]);

  const result = await login({ sessionDir, logger, io, timeoutMs: 20 });

  expect(result).toBe<LoginResult>("failed");
  expect(printed.at(-1)).toContain("Timed out");
});
