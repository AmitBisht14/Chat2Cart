import { describe, expect, it } from "vitest";
import { createLogger } from "../src/logger.js";

const config = { dbPath: "./data/chat2cart.sqlite", logLevel: "info" } as const;

function captureLogs(): { lines: string[]; write: (chunk: string) => void } {
  const lines: string[] = [];
  return { lines, write: (chunk) => void lines.push(chunk) };
}

function firstEntry(lines: readonly string[]): Record<string, unknown> {
  return JSON.parse(lines[0] ?? "{}") as Record<string, unknown>;
}

describe("createLogger", () => {
  it("writes_timestamp_level_run_id_and_event", () => {
    const output = captureLogs();

    createLogger(config, output).info({ items: 2 }, "cart_updated");

    expect(firstEntry(output.lines)).toMatchObject({
      level: "info",
      run_id: "-",
      event: "cart_updated",
      items: 2,
    });
    expect(firstEntry(output.lines)["ts"]).toEqual(expect.any(String));
  });

  it("masks_a_bearer_token_in_a_field_and_in_the_message", () => {
    const output = captureLogs();

    createLogger(config, output).info(
      { detail: "retry using Bearer abc.def now" },
      "called with Bearer abc.def",
    );

    expect(output.lines.join("")).not.toContain("abc.def");
    expect(output.lines.join("")).toContain("[redacted]");
  });

  it("redacts_known_secret_fields", () => {
    const output = captureLogs();

    createLogger(config, output).info(
      { token: "secret-1", headers: { authorization: "secret-2" } },
      "request_sent",
    );

    expect(output.lines.join("")).not.toMatch(/secret-[12]/);
  });
});
