/**
 * 描述: 共享错误码与标准错误类型
 * 主要功能:
 *     - 固定 Phase 1 公共错误码集合
 *     - 将未知异常转换为统一的 LawchersError
 */

export const errorCodes = [
  "MISSING_FIELD",
  "INVALID_INPUT",
  "CONFIG_INVALID",
  "IO_ERROR",
  "PROVIDER_UNAVAILABLE",
  "PROVIDER_DISABLED",
  "TIMEOUT",
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
