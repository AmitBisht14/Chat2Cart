import { pathToFileURL } from "node:url";
import type { Logger } from "pino";
import { loadConfig } from "./config.js";
import type { ListenerConfig } from "./config.js";
import { createLogger } from "./logger.js";

export const SERVICE_NAME = "chat2cart-listener";

export type ListenerContext = {
  readonly config: ListenerConfig;
  readonly logger: Logger;
};

export function start(): ListenerContext {
  const config = loadConfig();
  const logger = createLogger(config);
  logger.info("listener_started");
  return { config, logger };
}

const entryPoint = process.argv[1];
if (entryPoint !== undefined && import.meta.url === pathToFileURL(entryPoint).href) {
  start();
}
