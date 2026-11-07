import makeWASocket from "@whiskeysockets/baileys";
import type { AuthenticationState, WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";
import { z } from "zod";

const disconnectError = z.object({ output: z.object({ statusCode: z.number() }) });

export function createSocket(auth: AuthenticationState, logger: Logger): WASocket {
  return makeWASocket({
    auth,
    markOnlineOnConnect: false,
    // Baileys logs at debug level with message details; keep only its warnings and errors.
    logger: logger.child({ component: "baileys" }, { level: "warn" }),
  });
}

export function statusCodeOf(error: unknown): number | undefined {
  const parsed = disconnectError.safeParse(error);
  return parsed.success ? parsed.data.output.statusCode : undefined;
}
