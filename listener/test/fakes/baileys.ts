import { vi } from "vitest";
import { createFakeSocket } from "./fakeSocket.js";
import type { FakeSocket } from "./fakeSocket.js";

export const STATUS_CONNECTION_LOST = 408;
export const STATUS_LOGGED_OUT = 401;
export const STATUS_RESTART_REQUIRED = 515;

export const fakeBaileys = {
  sockets: [] as FakeSocket[],
  saveCreds: vi.fn(),
  useMultiFileAuthState: vi.fn(),
};

export function resetFakeBaileys(): void {
  fakeBaileys.sockets.length = 0;
  fakeBaileys.saveCreds.mockReset().mockResolvedValue(undefined);
  fakeBaileys.useMultiFileAuthState
    .mockReset()
    .mockResolvedValue({ state: {}, saveCreds: fakeBaileys.saveCreds });
}

export function lastFakeSocket(): FakeSocket {
  const socket = fakeBaileys.sockets[fakeBaileys.sockets.length - 1];
  if (socket === undefined) throw new Error("No fake socket was created.");
  return socket;
}

export function emitClose(socket: FakeSocket, statusCode: number): void {
  socket.ev.emit("connection.update", {
    connection: "close",
    lastDisconnect: { error: { output: { statusCode } }, date: new Date() },
  });
}

// Used as the vi.mock factory result for "@whiskeysockets/baileys".
export function createBaileysMock(): Record<string, unknown> {
  return {
    default: vi.fn(() => {
      const socket = createFakeSocket();
      fakeBaileys.sockets.push(socket);
      return socket;
    }),
    DisconnectReason: {
      loggedOut: STATUS_LOGGED_OUT,
      connectionLost: STATUS_CONNECTION_LOST,
      restartRequired: STATUS_RESTART_REQUIRED,
    },
    useMultiFileAuthState: fakeBaileys.useMultiFileAuthState,
  };
}
