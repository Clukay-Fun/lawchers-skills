import { mkdir, mkdtemp, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LawchersError } from "@lawchers/shared-core";
import { withFileLock } from "../src/index.js";

describe("file locks", () => {
  it("runs work while holding a lock", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-lock-"));
    const result = await withFileLock(path.join(root, "store.lock"), async () => "done");

    expect(result).toBe("done");
  });

  it("times out when the lock is already held", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-lock-"));
    const lockPath = path.join(root, "store.lock");

    await expect(
      withFileLock(lockPath, async () =>
        withFileLock(lockPath, async () => "never", { timeoutMs: 20, retryMs: 5 })
      )
    ).rejects.toMatchObject<Partial<LawchersError>>({ code: "LOCK_TIMEOUT" });
  });

  it("counts retry waiting toward timeout", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-lock-"));
    const lockPath = path.join(root, "store.lock");
    const startedAt = Date.now();

    await expect(
      withFileLock(lockPath, async () =>
        withFileLock(lockPath, async () => "never", { timeoutMs: 50, retryMs: 20 })
      )
    ).rejects.toMatchObject<Partial<LawchersError>>({ code: "LOCK_TIMEOUT" });

    expect(Date.now() - startedAt).toBeGreaterThanOrEqual(40);
  });

  it("cleans up stale locks", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-stale-lock-"));
    const lockPath = path.join(root, "store.lock");
    const lockDir = `${lockPath}.lock`;
    await writeFile(lockPath, "");
    await mkdir(lockDir);
    const staleTime = new Date(Date.now() - 10_000);
    await utimes(lockDir, staleTime, staleTime);

    await expect(withFileLock(lockPath, async () => "done", { staleMs: 2000 })).resolves.toBe("done");
  });
});
