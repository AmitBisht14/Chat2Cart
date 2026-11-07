import { pathToFileURL } from "node:url";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { loadConfig } from "./config.js";
import type { ListenerConfig } from "./config.js";
import { DatabaseSchemaError, openDatabase } from "./db.js";
import { createLogger } from "./logger.js";

export const SERVICE_NAME = "chat2cart-listener";
const SCHEMA_ERROR_EXIT_CODE = 1;

export type ListenerContext = {
  readonly config: ListenerConfig;
  readonly logger: Logger;
  readonly db: Database.Database;
};

export function start(): ListenerContext {
  const config = loadConfig();
  const db = openDatabaseOrExit(config.dbPath);
  const logger = createLogger(config);
  logger.info("listener_started");
  return { config, logger, db };
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
