import { defineConfig } from "vitest/config";

export const config = defineConfig({ test: { include: ["test/**/*.test.ts"] } });
export default config;
