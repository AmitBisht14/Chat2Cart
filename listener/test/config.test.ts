import { describe, expect, it } from "vitest";
import { parseConfig } from "../src/config.js";

const validEnv = {
  CHAT2CART_SENDER_PHONE: "919876543210",
  CHAT2CART_WA_SESSION_DIR: "./wa-session",
  CHAT2CART_DB_PATH: "./data/chat2cart.sqlite",
};

function errorsFor(env: NodeJS.ProcessEnv): readonly string[] {
  const result = parseConfig(env);
  return result.ok ? [] : result.errors;
}

describe("parseConfig", () => {
  it("returns_typed_config_for_a_valid_env", () => {
    expect(parseConfig(validEnv)).toEqual({
      ok: true,
      config: {
        senderPhone: "919876543210",
        sessionDir: "./wa-session",
        dbPath: "./data/chat2cart.sqlite",
        logLevel: "info",
      },
    });
  });

  it.each(Object.keys(validEnv))("names_the_missing_variable_%s", (name) => {
    const env: NodeJS.ProcessEnv = { ...validEnv };
    delete env[name];

    expect(errorsFor(env).join("\n")).toContain(`${name}: `);
  });

  it.each([
    ["CHAT2CART_SENDER_PHONE", "12345"],
    ["CHAT2CART_LOG_LEVEL", "LOUD"],
  ])("rejects_an_invalid_%s", (name, value) => {
    expect(errorsFor({ ...validEnv, [name]: value }).join("\n")).toContain(`${name}: `);
  });

  it.each(["+91 98765-43210", "0091 9876543210"])("normalises_phone_%s", (raw) => {
    const result = parseConfig({ ...validEnv, CHAT2CART_SENDER_PHONE: raw });

    expect(result.ok && result.config.senderPhone).toBe("919876543210");
  });

  it("accepts_the_agent_log_level_spelling", () => {
    const result = parseConfig({ ...validEnv, CHAT2CART_LOG_LEVEL: "WARNING" });

    expect(result.ok && result.config.logLevel).toBe("warn");
  });
});
