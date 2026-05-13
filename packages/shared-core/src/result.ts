import type { ErrorCode } from "./errors.js";
import { toLawchersError } from "./errors.js";

export interface SuccessResult<T> {
  ok: true;
  result: T;
  warnings: string[];
}

export interface ErrorResult {
  ok: false;
  code: ErrorCode;
  message: string;
  details: Record<string, unknown>;
}

export type CliResult<T> = SuccessResult<T> | ErrorResult;

export function ok<T>(result: T, warnings: string[] = []): SuccessResult<T> {
  return { ok: true, result, warnings };
}

export function fail(
  code: ErrorCode,
  message: string,
  details: Record<string, unknown> = {}
): ErrorResult {
  return { ok: false, code, message, details };
}

export function errorToResult(error: unknown, env: NodeJS.ProcessEnv = process.env): ErrorResult {
  const lawchersError = toLawchersError(error);
  const details: Record<string, unknown> = { ...(lawchersError.details ?? {}) };

  if (env.LAWCHERS_DEBUG === "1" && lawchersError.stack) {
    details.stack = lawchersError.stack;
  }

  return fail(lawchersError.code, lawchersError.message, details);
}
