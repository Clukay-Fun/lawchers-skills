import { describe, expect, it } from "vitest";
import { errorCodes, errorToResult, fail, LawchersError, ok } from "../src/index.js";

describe("result helpers", () => {
  it("creates success results", () => {
    expect(ok({ value: 1 })).toEqual({
      ok: true,
      result: { value: 1 },
      warnings: []
    });
  });

  it("creates error results", () => {
    expect(fail("MISSING_FIELD", "Missing value", { field: "name" })).toEqual({
      ok: false,
      code: "MISSING_FIELD",
      message: "Missing value",
      details: { field: "name" }
    });
  });

  it("freezes the phase 1 error code set", () => {
    expect(errorCodes).toEqual([
      "MISSING_FIELD",
      "INVALID_INPUT",
      "CONFIG_INVALID",
      "IO_ERROR",
      "LOCK_TIMEOUT",
      "PROVIDER_UNAVAILABLE",
      "PROVIDER_DISABLED",
      "TIMEOUT",
      "PARSE_FAILED",
      "LOW_CONFIDENCE",
      "UNKNOWN"
    ]);
  });

  it("does not include stack details unless debug is enabled", () => {
    const error = new LawchersError("INVALID_INPUT", "Nope");

    expect(errorToResult(error, {})).toEqual({
      ok: false,
      code: "INVALID_INPUT",
      message: "Nope",
      details: {}
    });

    expect(errorToResult(error, { LAWCHERS_DEBUG: "1" }).details.stack).toContain("LawchersError");
  });
});
