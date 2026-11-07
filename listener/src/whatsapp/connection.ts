import { DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import type { BaileysEventMap, WAMessage, WASocket } from "@whiskeysockets/baileys";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { createSocket, statusCodeOf } from "./socket.js";
import { startHeartbeat, writeState } from "./state.js";
import type { WhatsAppState } from "./state.js";

export const BASE_RETRY_DELAY_MS = 500;
export const MAX_RETRY_DELAY_MS = 30_000;
export const LOGGED_OUT_DETAIL = "Run chat2cart-wa login";
const IDLE_INTERVAL_MS = 60 * 60 * 1000;

export type ConnectionOptions = {
  readonly sessionDir: string;
  readonly logger: Logger;
  readonly db: Database.Database;
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
  isLoggedOut: boolean;
  stopHeartbeat: (() => void) | undefined;
  idleTimer: NodeJS.Timeout | undefined;
};

export function startConnection(options: ConnectionOptions): Connection {
  const session: Session = {
    socket: undefined,
    timer: undefined,
    retries: 0,
    isStopped: false,
    isLoggedOut: false,
    stopHeartbeat: undefined,
    idleTimer: undefined,
  };
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
  const socket = createSocket(state, options.logger);
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
  if (update.connection === "open") handleOpen(options, session);
  if (update.connection === "close") handleClose(update, options, session);
}

function handleOpen(options: ConnectionOptions, session: Session): void {
  session.retries = 0;
  options.logger.info("whatsapp_connected");
  recordState(options, "connected");
  session.stopHeartbeat?.();
  session.stopHeartbeat = startHeartbeat({ db: options.db, logger: options.logger });
}

function handleClose(
  update: BaileysEventMap["connection.update"],
  options: ConnectionOptions,
  session: Session,
): void {
  session.stopHeartbeat?.();
  session.stopHeartbeat = undefined;
  const statusCode = statusCodeOf(update.lastDisconnect?.error);
  if (statusCode === DisconnectReason.loggedOut) {
    handleLoggedOut(options, session);
    return;
  }
  options.logger.warn({ statusCode }, "whatsapp_connection_closed");
  recordState(options, "reconnecting", `connection closed (status ${String(statusCode)})`);
  scheduleReconnect(options, session);
}

function handleLoggedOut(options: ConnectionOptions, session: Session): void {
  session.isLoggedOut = true;
  clearTimeout(session.timer);
  options.logger.error("whatsapp_logged_out");
  recordState(options, "logged_out", LOGGED_OUT_DETAIL);
  // A ref'd timer keeps the process alive and idle, so pm2 does not restart-loop it.
  session.idleTimer = setInterval(() => undefined, IDLE_INTERVAL_MS);
}

function recordState(options: ConnectionOptions, state: WhatsAppState, detail?: string): void {
  try {
    writeState({ db: options.db, logger: options.logger }, state, detail);
  } catch (error) {
    options.logger.error({ err: error }, "whatsapp_state_write_failed");
  }
}

function scheduleReconnect(options: ConnectionOptions, session: Session): void {
  if (session.isStopped || session.isLoggedOut) return;
  const delay = Math.min(MAX_RETRY_DELAY_MS, BASE_RETRY_DELAY_MS * 2 ** session.retries);
  session.retries += 1;
  session.timer = setTimeout(() => {
    connect(options, session);
  }, delay);
}

function stop(session: Session, logger: Logger): void {
  session.isStopped = true;
  clearTimeout(session.timer);
  clearInterval(session.idleTimer);
  session.stopHeartbeat?.();
  session.socket?.end(undefined).catch((error: unknown) => {
    logger.error({ err: error }, "whatsapp_socket_end_failed");
  });
}
