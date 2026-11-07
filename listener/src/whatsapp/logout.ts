import { rm } from "node:fs/promises";
import { useMultiFileAuthState } from "@whiskeysockets/baileys";
import type { WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";
import { isRegistered } from "./login.js";
import type { LoginIo } from "./login.js";
import { createSocket } from "./socket.js";

export const OPEN_TIMEOUT_MS = 30_000;
export const NO_SESSION_MESSAGE = "No WhatsApp session found. Nothing to log out.";
export const CONFIRM_QUESTION = "Unlink this device and delete the local session? [y/N] ";
export const LOGGED_OUT_MESSAGE =
  "Logged out. The device is unlinked and the local session is deleted.";
export const SESSION_REMOVED_ONLY_MESSAGE =
  "Could not reach WhatsApp, so the device may still be linked. The local session is deleted; " +
  "remove this device on your phone under WhatsApp > Settings > Linked devices.";

const CONFIRMING_ANSWERS = new Set(["y", "yes"]);

export type LogoutIo = Pick<LoginIo, "ask" | "print">;

export type LogoutOptions = {
  readonly sessionDir: string;
  readonly logger: Logger;
  readonly io: LogoutIo;
  readonly recordLoggedOut: () => void;
  readonly timeoutMs?: number;
};

export type LogoutResult = "logged_out" | "session_removed_only" | "cancelled" | "no_session";

export async function logoutDevice(options: LogoutOptions): Promise<LogoutResult> {
  const { io, sessionDir } = options;
  if (!isRegistered(sessionDir)) {
    io.print(NO_SESSION_MESSAGE);
    return "no_session";
  }
  if (!(await isConfirmed(io))) return "cancelled";
  const wasUnlinked = await unlinkFromWhatsApp(options);
  await rm(sessionDir, { recursive: true, force: true });
  options.recordLoggedOut();
  io.print(wasUnlinked ? LOGGED_OUT_MESSAGE : SESSION_REMOVED_ONLY_MESSAGE);
  return wasUnlinked ? "logged_out" : "session_removed_only";
}

async function isConfirmed(io: LogoutIo): Promise<boolean> {
  const answer = (await io.ask(CONFIRM_QUESTION)).trim().toLowerCase();
  return CONFIRMING_ANSWERS.has(answer);
}

async function unlinkFromWhatsApp(options: LogoutOptions): Promise<boolean> {
  const { logger } = options;
  try {
    const { state } = await useMultiFileAuthState(options.sessionDir);
    const socket = createSocket(state, logger);
    try {
      await waitUntilOpen(socket, options.timeoutMs ?? OPEN_TIMEOUT_MS);
      await socket.logout();
      return true;
    } finally {
      await endQuietly(socket, logger);
    }
  } catch (error) {
    logger.error({ err: error }, "whatsapp_logout_failed");
    return false;
  }
}

function waitUntilOpen(socket: WASocket, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error("Timed out waiting for the WhatsApp connection."));
    }, timeoutMs);
    socket.ev.on("connection.update", (update) => {
      if (update.connection === "open") {
        clearTimeout(timer);
        resolve();
      }
      if (update.connection === "close") {
        clearTimeout(timer);
        reject(new Error("WhatsApp closed the connection."));
      }
    });
  });
}

async function endQuietly(socket: WASocket, logger: Logger): Promise<void> {
  try {
    await socket.end(undefined);
  } catch (error) {
    logger.error({ err: error }, "whatsapp_socket_end_failed");
  }
}
