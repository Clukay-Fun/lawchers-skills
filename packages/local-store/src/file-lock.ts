import { promises as fs } from "node:fs";
import path from "node:path";
import { LawchersError } from "@lawchers/shared-core";
import lockfile from "proper-lockfile";

export interface FileLockOptions {
  timeoutMs?: number;
  retryMs?: number;
  staleMs?: number;
}

export const defaultFileLockOptions = {
  timeoutMs: 5000,
  retryMs: 25,
  staleMs: 10000
} as const;

export async function withFileLock<T>(
  lockPath: string,
  fn: () => Promise<T>,
  options: FileLockOptions = {}
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? defaultFileLockOptions.timeoutMs;
  const retryMs = options.retryMs ?? defaultFileLockOptions.retryMs;
  const staleMs = options.staleMs ?? defaultFileLockOptions.staleMs;
  const startedAt = Date.now();
  let release: (() => Promise<void>) | undefined;

  await fs.mkdir(path.dirname(lockPath), { recursive: true });
  await fs.writeFile(lockPath, "", { flag: "a" });

  while (!release) {
    try {
      release = await lockfile.lock(lockPath, {
        realpath: false,
        retries: 0,
        stale: staleMs
      });
    } catch (error) {
      if (!isNodeError(error) || error.code !== "ELOCKED") {
        throw new LawchersError("IO_ERROR", `Failed to acquire lock: ${lockPath}`, {
          path: lockPath
        }, error);
      }

      if (Date.now() - startedAt >= timeoutMs) {
        throw new LawchersError("LOCK_TIMEOUT", `Timed out acquiring lock: ${lockPath}`, {
          path: lockPath,
          timeoutMs
        });
      }

      await delay(retryMs);
    }
  }

  try {
    return await fn();
  } finally {
    await release();
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
