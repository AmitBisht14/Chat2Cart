import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import type { BaileysEventMap, WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";
import { z } from "zod";
import { createSocket, statusCodeOf } from "./socket.js";

export const LOGIN_TIMEOUT_MS = 3 * 60 * 1000;
export const ALREADY_LINKED_MESSAGE =
  "A WhatsApp session already exists. Run `chat2cart-wa logout` first to link again.";
export const QR_STEPS =
  "On your phone: WhatsApp > Settings > Linked devices > Link a device, then scan this code.";
export const PAIRING_STEPS =
  "On your phone: WhatsApp > Settings > Linked devices > Link a device > Link with phone number instead, then enter this code.";

const CREDS_FILE = "creds.json";
const PHONE_PATTERN = /^\d{10,15}$/;
const registeredCreds = z.object({ registered: z.boolean() });

export type LoginIo = {
  readonly ask: (question: string) => Promise<string>;
  readonly print: (line: string) => void;
  readonly renderQr: (qr: string) => string;
};

export type LoginOptions = {
  readonly sessionDir: string;
  readonly logger: Logger;
  readonly io: LoginIo;
  readonly timeoutMs?: number;
};

export type LoginResult = "linked" | "already_linked" | "failed";

type Method = { readonly kind: "qr" } | { readonly kind: "pairing"; readonly phone: string };

type Flow = {
  readonly options: LoginOptions;
  readonly method: Method;
  readonly finish: (result: LoginResult) => void;
  socket: WASocket | undefined;
  pendingSave: Promise<void>;
  hasRestarted: boolean;
  hasShownQrSteps: boolean;
  hasRequestedCode: boolean;
};

export async function login(options: LoginOptions): Promise<LoginResult> {
  if (isRegistered(options.sessionDir)) {
    options.io.print(ALREADY_LINKED_MESSAGE);
    return "already_linked";
  }
  const method = await chooseMethod(options.io);
  return linkDevice(options, method);
}

function isRegistered(sessionDir: string): boolean {
  const file = path.join(sessionDir, CREDS_FILE);
  if (!existsSync(file)) return false;
  const parsed = registeredCreds.safeParse(readJson(file));
  return parsed.success && parsed.data.registered;
}

function readJson(file: string): unknown {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    // A damaged creds file means there is no usable session; linking again rewrites it.
    if (error instanceof SyntaxError) return undefined;
    throw error;
  }
}

async function chooseMethod(io: LoginIo): Promise<Method> {
  for (;;) {
    const answer = (await io.ask("Link with (1) QR code or (2) pairing code? ")).trim();
    if (answer === "1") return { kind: "qr" };
    if (answer === "2") return { kind: "pairing", phone: await askPhone(io) };
    io.print("Enter 1 or 2.");
  }
}

async function askPhone(io: LoginIo): Promise<string> {
  for (;;) {
    const phone = (
      await io.ask("Phone number with country code, no plus sign (digits only, 10 to 15): ")
    ).trim();
    if (PHONE_PATTERN.test(phone)) return phone;
    io.print("That is not a valid number. Use digits only, for example 919876543210.");
  }
}

function linkDevice(options: LoginOptions, method: Method): Promise<LoginResult> {
  return new Promise((resolve) => {
    const flow: Flow = {
      options,
      method,
      finish: (result) => {
        clearTimeout(timer);
        endSocket(flow);
        resolve(result);
      },
      socket: undefined,
      pendingSave: Promise.resolve(),
      hasRestarted: false,
      hasShownQrSteps: false,
      hasRequestedCode: false,
    };
    const timer = setTimeout(() => {
      options.io.print("Timed out waiting for the link. Run the command again.");
      flow.finish("failed");
    }, options.timeoutMs ?? LOGIN_TIMEOUT_MS);
    startSocket(flow);
  });
}

function startSocket(flow: Flow): void {
  openSocket(flow).catch((error: unknown) => {
    flow.options.logger.error({ err: error }, "whatsapp_login_failed");
    flow.options.io.print("Could not start the WhatsApp connection. Run the command again.");
    flow.finish("failed");
  });
}

async function openSocket(flow: Flow): Promise<void> {
  const { state, saveCreds } = await useMultiFileAuthState(flow.options.sessionDir);
  const socket = createSocket(state, flow.options.logger);
  flow.socket = socket;
  socket.ev.on("creds.update", () => {
    flow.pendingSave = flow.pendingSave
      .then(() => saveCreds())
      .catch((error: unknown) => {
        flow.options.logger.error({ err: error }, "whatsapp_credentials_save_failed");
      });
  });
  socket.ev.on("connection.update", (update) => {
    handleConnectionUpdate(flow, update);
  });
}

function handleConnectionUpdate(flow: Flow, update: BaileysEventMap["connection.update"]): void {
  if (update.qr !== undefined) handleQr(flow, update.qr);
  if (update.connection === "open") finishWhenSaved(flow);
  if (update.connection === "close") handleClose(flow, update);
}

function handleQr(flow: Flow, qr: string): void {
  if (flow.method.kind === "pairing") {
    requestPairingCode(flow, flow.method.phone);
    return;
  }
  const { io } = flow.options;
  if (!flow.hasShownQrSteps) {
    io.print(QR_STEPS);
    flow.hasShownQrSteps = true;
  }
  io.print(io.renderQr(qr));
}

// Baileys only accepts a pairing request once the socket is ready, which its first qr event signals.
function requestPairingCode(flow: Flow, phone: string): void {
  if (flow.hasRequestedCode || flow.socket === undefined) return;
  flow.hasRequestedCode = true;
  flow.socket
    .requestPairingCode(phone)
    .then((code) => {
      flow.options.io.print(`Pairing code: ${code}`);
      flow.options.io.print(PAIRING_STEPS);
    })
    .catch((error: unknown) => {
      flow.options.logger.error({ err: error }, "whatsapp_pairing_code_failed");
      flow.options.io.print("Could not get a pairing code. Run the command again.");
      flow.finish("failed");
    });
}

function handleClose(flow: Flow, update: BaileysEventMap["connection.update"]): void {
  const statusCode = statusCodeOf(update.lastDisconnect?.error);
  if (statusCode === DisconnectReason.restartRequired && !flow.hasRestarted) {
    flow.hasRestarted = true;
    // The new socket reads the session from disk, so wait for the pending credentials save.
    void flow.pendingSave.then(() => {
      startSocket(flow);
    });
    return;
  }
  flow.options.io.print("WhatsApp closed the connection before linking finished. Run it again.");
  flow.finish("failed");
}

function finishWhenSaved(flow: Flow): void {
  void flow.pendingSave.then(() => {
    flow.options.io.print("Linked. Session saved.");
    flow.finish("linked");
  });
}

function endSocket(flow: Flow): void {
  flow.socket?.end(undefined).catch((error: unknown) => {
    flow.options.logger.error({ err: error }, "whatsapp_socket_end_failed");
  });
}
