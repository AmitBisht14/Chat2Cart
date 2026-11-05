import path from "node:path";
import dotenv from "dotenv";
import { z } from "zod";

export const CONFIG_ERROR_EXIT_CODE = 2;

const ENV_PREFIX = "CHAT2CART_";
const ENV_FILE = path.resolve(import.meta.dirname, "..", "..", ".env");
const MIN_PHONE_DIGITS = 11;
const MAX_PHONE_DIGITS = 15;

export function normalizePhone(raw: string): string | undefined {
  const digits = raw.replace(/\D/g, "").replace(/^00/, "");
  const isValidLength = digits.length >= MIN_PHONE_DIGITS && digits.length <= MAX_PHONE_DIGITS;
  return isValidLength ? digits : undefined;
}

const phoneSchema = z.string().transform((raw, context) => {
  const phone = normalizePhone(raw);
  if (phone === undefined) {
    context.addIssue({
      code: "custom",
      message: `phone number must have ${MIN_PHONE_DIGITS} to ${MAX_PHONE_DIGITS} digits including the country code`,
    });
    return z.NEVER;
  }
  return phone;
});

const logLevelSchema = z
  .string()
  .default("info")
  .transform((value) => value.toLowerCase())
  .pipe(z.enum(["debug", "info", "warning", "error"]))
  .transform((level) => (level === "warning" ? "warn" : level));

const envSchema = z.object({
  CHAT2CART_SENDER_PHONE: phoneSchema,
  CHAT2CART_WA_SESSION_DIR: z.string().min(1),
  CHAT2CART_DB_PATH: z.string().min(1),
  CHAT2CART_LOG_LEVEL: logLevelSchema,
});

export type ListenerConfig = {
  readonly senderPhone: string;
  readonly sessionDir: string;
  readonly dbPath: string;
  readonly logLevel: "debug" | "info" | "warn" | "error";
};

export type ConfigResult =
  | { readonly ok: true; readonly config: ListenerConfig }
  | { readonly ok: false; readonly errors: readonly string[] };

export function parseConfig(env: NodeJS.ProcessEnv): ConfigResult {
  const result = envSchema.safeParse(withoutEmptyValues(env));
  if (!result.success) {
    return { ok: false, errors: result.error.issues.map(formatIssue) };
  }
  const values = result.data;
  return {
    ok: true,
    config: {
      senderPhone: values.CHAT2CART_SENDER_PHONE,
      sessionDir: values.CHAT2CART_WA_SESSION_DIR,
      dbPath: values.CHAT2CART_DB_PATH,
      logLevel: values.CHAT2CART_LOG_LEVEL,
    },
  };
}

export function loadConfig(): ListenerConfig {
  dotenv.config({ path: ENV_FILE, quiet: true });
  const result = parseConfig(process.env);
  if (result.ok) return result.config;
  for (const line of result.errors) process.stderr.write(`${line}\n`);
  process.exit(CONFIG_ERROR_EXIT_CODE);
}

function withoutEmptyValues(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return Object.fromEntries(Object.entries(env).filter(([, value]) => value !== ""));
}

function formatIssue(issue: z.core.$ZodIssue): string {
  const name = issue.path.length > 0 ? issue.path.join(".") : ENV_PREFIX;
  return `${name}: ${issue.message}`;
}
