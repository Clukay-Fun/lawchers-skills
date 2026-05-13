export const errorCodes = [
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
] as const;

export type ErrorCode = (typeof errorCodes)[number];

export class LawchersError extends Error {
  readonly code: ErrorCode;
  readonly details?: Record<string, unknown>;
  override readonly cause?: unknown;

  constructor(code: ErrorCode, message: string, details?: Record<string, unknown>, cause?: unknown) {
    super(message, { cause });
    this.name = "LawchersError";
    this.code = code;
    this.details = details;
    this.cause = cause;
  }
}

export function toLawchersError(error: unknown): LawchersError {
  if (error instanceof LawchersError) {
    return error;
  }

  if (error instanceof Error) {
    return new LawchersError("UNKNOWN", error.message, undefined, error);
  }

  return new LawchersError("UNKNOWN", "Unexpected error");
}
