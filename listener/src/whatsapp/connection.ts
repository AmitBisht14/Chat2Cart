import makeWASocket, { DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import type { BaileysEventMap, WAMessage, WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";
import { z } from "zod";

export const BASE_RETRY_DELAY_MS = 500;
export const MAX_RETRY_DELAY_MS = 30_000;

export type ConnectionOptions = {
  readonly sessionDir: string;
  readonly logger: Logger;
  readonly onMessage: (message: WAMessage) => void | Promise<void>;
};

export type Connection = {
  readonly stop: () => void;
};

type Session = {
  socket: WASocket | undefined;
  timer: NodeJS.Timeout | undefined;
  retries: number;
  isStopped: boolean;
};

const disconnectError = z.object({ output: z.object({ statusCode: z.number() }) });

export function startConnection(options: ConnectionOptions): Connection {
  const session: Session = { socket: undefined, timer: undefined, retries: 0, isStopped: false };
  connect(options, session);
  return { stop: () => stop(session, options.logger) };
}

function connect(options: ConnectionOptions, session: Session): void {
  openSocket(options, session).catch((error: unknown) => {
    options.logger.error({ err: error }, "whatsapp_connect_failed");
    scheduleReconnect(options, session);
  });
}

async function openSocket(options: ConnectionOptions, session: Session): Promise<void> {
  const { state, saveCreds } = await useMultiFileAuthState(options.sessionDir);
  if (session.isStopped) return;
  const socket = makeWASocket({
    auth: state,
    markOnlineOnConnect: false,
    // Baileys logs at debug level with message details; keep only its warnings and errors.
    logger: options.logger.child({ component: "baileys" }, { level: "warn" }),
  });
  session.socket = socket;
  socket.ev.on("creds.update", () => {
    saveCreds().catch((error: unknown) => {
      options.logger.error({ err: error }, "whatsapp_credentials_save_failed");
    });
  });
  socket.ev.on("messages.upsert", (upsert) => {
    if (upsert.type === "notify") void deliverMessages(upsert.messages, options);
  });
  socket.ev.on("connection.update", (update) => {
    handleConnectionUpdate(update, options, session);
  });
}

async function deliverMessages(
  messages: readonly WAMessage[],
  options: ConnectionOptions,
): Promise<void> {
  for (const message of messages) {
    try {
      await options.onMessage(message);
    } catch (error) {
      options.logger.error({ err: error }, "intake_handler_failed");
    }
  }
}

function handleConnectionUpdate(
  update: BaileysEventMap["connection.update"],
  options: ConnectionOptions,
  session: Session,
): void {
  if (update.connection === "open") {
    session.retries = 0;
    options.logger.info("whatsapp_connected");
    return;
  }
  if (update.connection !== "close") return;
  const statusCode = statusCodeOf(update.lastDisconnect?.error);
  if (statusCode === DisconnectReason.loggedOut) {
    options.logger.error("whatsapp_logged_out");
    return;
  }
  options.logger.warn({ statusCode }, "whatsapp_connection_closed");
  scheduleReconnect(options, session);
}

function statusCodeOf(error: unknown): number | undefined {
  const parsed = disconnectError.safeParse(error);
  return parsed.success ? parsed.data.output.statusCode : undefined;
}

function scheduleReconnect(options: ConnectionOptions, session: Session): void {
  if (session.isStopped) return;
  const delay = Math.min(MAX_RETRY_DELAY_MS, BASE_RETRY_DELAY_MS * 2 ** session.retries);
  session.retries += 1;
  session.timer = setTimeout(() => {
    connect(options, session);
  }, delay);
}

function stop(session: Session, logger: Logger): void {
  session.isStopped = true;
  clearTimeout(session.timer);
  session.socket?.end(undefined).catch((error: unknown) => {
    logger.error({ err: error }, "whatsapp_socket_end_failed");
  });
}
