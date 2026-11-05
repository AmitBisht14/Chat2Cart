import { pathToFileURL } from "node:url";
import { loadConfig } from "./config.js";
import type { ListenerConfig } from "./config.js";

export const SERVICE_NAME = "chat2cart-listener";

export function start(): ListenerConfig {
  return loadConfig();
}

const entryPoint = process.argv[1];
if (entryPoint !== undefined && import.meta.url === pathToFileURL(entryPoint).href) {
  start();
}
