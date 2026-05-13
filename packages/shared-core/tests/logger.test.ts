import { describe, expect, it } from "vitest";
import { createLogger } from "../src/index.js";

describe("logger", () => {
  it("writes json lines at or above the configured level", () => {
    const lines: string[] = [];
    const logger = createLogger({
      level: "info",
      env: { LAWCHERS_TRACE_ID: "trace-from-env" },
      pkg: "@lawchers/kb",
      sink: (line) => lines.push(line),
      now: () => new Date("2026-05-13T10:00:00.000Z")
    });

    logger.debug("hidden", "not written");
    logger.info("sqlite.open", "opened database", { db: "kb" });

    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0] ?? "{}")).toEqual({
      ts: "2026-05-13T10:00:00.000Z",
      level: "info",
      msg: "opened database",
      pkg: "@lawchers/kb",
      event: "sqlite.open",
      traceId: "trace-from-env",
      details: { db: "kb" }
    });
  });

  it("prefers explicit trace ids over environment trace ids", () => {
    const lines: string[] = [];
    const logger = createLogger({
      level: "info",
      traceId: "explicit",
      env: { LAWCHERS_TRACE_ID: "env" },
      pkg: "@lawchers/kb",
      sink: (line) => lines.push(line)
    });

    logger.info("event", "message");

    expect(JSON.parse(lines[0] ?? "{}").traceId).toBe("explicit");
  });
});
