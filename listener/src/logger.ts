import path from "node:path";
import { pino } from "pino";
import type { DestinationStream, Logger } from "pino";
import type { ListenerConfig } from "./config.js";

const LOG_FILE_NAME = "listener.log";
const LOG_MAX_SIZE = "10m";
const LOG_FILES_TO_KEEP = 5;
const DEFAULT_RUN_ID = "-";
const REDACTED = "[redacted]";
const SECRET_KEYS = [
  "token",
  "access_token",
  "refresh_token",
  "authorization",
  "api_key",
  "otp",
  "code_verifier",
  "session_key",
] as const;
const REDACT_PATHS = [
  ...SECRET_KEYS,
  ...SECRET_KEYS.map((key) => `*.${key}`),
  "headers.authorization",
  "headers.Authorization",
];
const BEARER_PATTERN = /Bearer\s+[\w.~+/=-]+/gi;

export function createLogger(
  config: Pick<ListenerConfig, "dbPath" | "logLevel">,
  destination: DestinationStream = rollingFileDestination(config.dbPath),
): Logger {
  return pino(
    {
      level: config.logLevel,
      messageKey: "event",
      base: { run_id: DEFAULT_RUN_ID },
      timestamp: () => `,"ts":"${new Date().toISOString()}"`,
      formatters: {
        level: (label) => ({ level: label }),
        log: (fields) => maskBearerTokens(fields) as Record<string, unknown>,
      },
      redact: { paths: REDACT_PATHS, censor: REDACTED },
      hooks: {
        logMethod(args, method) {
          method.apply(this, args.map(maskBearerTokens) as Parameters<typeof method>);
        },
      },
    },
    destination,
  );
}

function rollingFileDestination(dbPath: string): DestinationStream {
  return pino.transport({
    target: "pino-roll",
    options: {
      file: path.join(path.dirname(dbPath), "logs", LOG_FILE_NAME),
      size: LOG_MAX_SIZE,
      limit: { count: LOG_FILES_TO_KEEP },
      mkdir: true,
    },
  });
}

function maskBearerTokens(value: unknown): unknown {
  if (typeof value === "string") return value.replace(BEARER_PATTERN, `Bearer ${REDACTED}`);
  if (Array.isArray(value)) return value.map(maskBearerTokens);
  if (!isPlainObject(value)) return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, maskBearerTokens(item)]),
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype
  );
}
