#!/usr/bin/env node
import { createInterface } from "node:readline/promises";
import { parseArgs } from "node:util";
import qrcode from "qrcode-terminal";
import type Database from "better-sqlite3";
import { loadConfig } from "./config.js";
import type { ListenerConfig } from "./config.js";
import { DatabaseSchemaError, openDatabase } from "./db.js";
import { createLogger } from "./logger.js";
import { login } from "./whatsapp/login.js";
import type { LoginIo } from "./whatsapp/login.js";
import { logoutDevice } from "./whatsapp/logout.js";
import { writeState } from "./whatsapp/state.js";

const USAGE = "Usage: chat2cart-wa <login|logout>";
const USER_LOGOUT_DETAIL = "user logout";
const USAGE_EXIT_CODE = 2;
const FAILURE_EXIT_CODE = 1;

async function main(argv: readonly string[]): Promise<number> {
  const command = parseCommand(argv);
  if (command === "login") return runLogin();
  if (command === "logout") return runLogout();
  process.stderr.write(`${USAGE}\n`);
  return USAGE_EXIT_CODE;
}

function parseCommand(argv: readonly string[]): string | undefined {
  try {
    const { positionals } = parseArgs({ args: [...argv], allowPositionals: true, options: {} });
    return positionals.length === 1 ? positionals[0] : undefined;
  } catch (error) {
    if (error instanceof TypeError) return undefined;
    throw error;
  }
}

async function runLogin(): Promise<number> {
  const config = loadConfig();
  const readline = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const result = await login({
      sessionDir: config.sessionDir,
      logger: createLogger(config),
      io: terminalIo(readline),
    });
    return result === "failed" ? FAILURE_EXIT_CODE : 0;
  } finally {
    readline.close();
  }
}

async function runLogout(): Promise<number> {
  const config = loadConfig();
  const logger = createLogger(config);
  const db = openDatabaseIfReady(config);
  const readline = createInterface({ input: process.stdin, output: process.stdout });
  try {
    await logoutDevice({
      sessionDir: config.sessionDir,
      logger,
      io: terminalIo(readline),
      recordLoggedOut: () => {
        if (db !== undefined) writeState({ db, logger }, "logged_out", USER_LOGOUT_DETAIL);
      },
    });
    return 0;
  } finally {
    readline.close();
    db?.close();
  }
}

// The agent owns the database; without it logout still works and only skips the state row.
function openDatabaseIfReady(config: ListenerConfig): Database.Database | undefined {
  try {
    return openDatabase(config.dbPath);
  } catch (error) {
    if (error instanceof DatabaseSchemaError) return undefined;
    throw error;
  }
}

function terminalIo(readline: ReturnType<typeof createInterface>): LoginIo {
  return {
    ask: (question) => readline.question(question),
    print: (line) => process.stdout.write(`${line}\n`),
    renderQr,
  };
}

function renderQr(qr: string): string {
  let rendered = "";
  qrcode.generate(qr, { small: true }, (code) => {
    rendered = code;
  });
  return rendered;
}

process.exit(await main(process.argv.slice(2)));
