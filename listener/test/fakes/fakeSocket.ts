import { EventEmitter } from "node:events";
import { vi } from "vitest";

export type FakeSocket = {
  readonly ev: EventEmitter;
  readonly end: ReturnType<typeof vi.fn>;
  readonly logout: ReturnType<typeof vi.fn>;
};

export function createFakeSocket(): FakeSocket {
  return {
    ev: new EventEmitter(),
    end: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
  };
}
