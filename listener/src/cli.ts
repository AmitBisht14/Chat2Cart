#!/usr/bin/env node
import { createInterface } from "node:readline/promises";
import { parseArgs } from "node:util";
import qrcode from "qrcode-terminal";
import { loadConfig } from "./config.js";
import { createLogger } from "./logger.js";
import { login } from "./whatsapp/login.js";
import type { LoginIo } from "./whatsapp/login.js";

const USAGE = "Usage: chat2cart-wa login";
const USAGE_EXIT_CODE = 2;
const FAILURE_EXIT_CODE = 1;

async function main(argv: readonly string[]): Promise<number> {
  const command = parseCommand(argv);
  if (command !== "login") {
    process.stderr.write(`${USAGE}\n`);
    return USAGE_EXIT_CODE;
  }
  return runLogin();
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
