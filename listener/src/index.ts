import { pathToFileURL } from "node:url";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { loadConfig } from "./config.js";
import type { ListenerConfig } from "./config.js";
import { DatabaseSchemaError, openDatabase } from "./db.js";
import { applyIntakeRules } from "./intake/rules.js";
import type { IntakeResult } from "./intake/rules.js";
import { senderFilter } from "./intake/senderFilter.js";
import { createLogger } from "./logger.js";
import { startConnection } from "./whatsapp/connection.js";
import type { Connection } from "./whatsapp/connection.js";

export const SERVICE_NAME = "chat2cart-listener";
const SCHEMA_ERROR_EXIT_CODE = 1;

export type ListenerContext = {
  readonly config: ListenerConfig;
  readonly logger: Logger;
  readonly db: Database.Database;
  readonly connection: Connection;
};

export function start(): ListenerContext {
  const config = loadConfig();
  const db = openDatabaseOrExit(config.dbPath);
  const logger = createLogger(config);
  logger.info("listener_started");
  const connection = startConnection({
    sessionDir: config.sessionDir,
    logger,
    db,
    onMessage: (message) => {
      const intake = applyIntakeRules(message);
      if (!intake.accept) {
        logIgnored(logger, intake, message.key.id);
        return;
      }
      if (!senderFilter({ db, logger, allowedPn: config.senderPhone }, message).accepted) return;
      logger.info({ messageId: message.key.id }, "message_received");
    },
  });
  return { config, logger, db, connection };
}

// Media and edits are worth an info line; the rest is routine noise. Never log the message text.
function logIgnored(
  logger: Logger,
  intake: Extract<IntakeResult, { accept: false }>,
  messageId: string | null | undefined,
): void {
  const level = intake.reason === "media" || intake.reason === "edit_or_delete" ? "info" : "debug";
  logger[level]({ reason: intake.reason, detail: intake.detail, messageId }, "intake_ignored");
}

function openDatabaseOrExit(dbPath: string): Database.Database {
  try {
    return openDatabase(dbPath);
  } catch (error) {
    if (!(error instanceof DatabaseSchemaError)) throw error;
    process.stderr.write(`${error.message}\n`);
    process.exit(SCHEMA_ERROR_EXIT_CODE);
  }
}

const entryPoint = process.argv[1];
if (entryPoint !== undefined && import.meta.url === pathToFileURL(entryPoint).href) {
  start();
}
