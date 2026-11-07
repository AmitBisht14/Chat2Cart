import { EventEmitter } from "node:events";
import { vi } from "vitest";

export type FakeSocket = {
  readonly ev: EventEmitter;
  readonly end: ReturnType<typeof vi.fn>;
  readonly logout: ReturnType<typeof vi.fn>;
  readonly requestPairingCode: ReturnType<typeof vi.fn>;
};

export const FAKE_PAIRING_CODE = "ABCD1234";

export function createFakeSocket(): FakeSocket {
  return {
    ev: new EventEmitter(),
    end: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    requestPairingCode: vi.fn().mockResolvedValue(FAKE_PAIRING_CODE),
  };
}
