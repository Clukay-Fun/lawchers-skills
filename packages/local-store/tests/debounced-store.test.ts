import { mkdtemp, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LawchersError } from "@lawchers/shared-core";
import { DebouncedJsonStore } from "../src/index.js";

describe("debounced json store", () => {
  it("flushes pending updates", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-debounced-"));
    const filePath = path.join(root, "store.json");
    const store = new DebouncedJsonStore<{ count: number }>({
      filePath,
      fallback: { count: 0 },
      debounceMs: 1000
    });

    await store.update((current) => ({ count: current.count + 1 }));
    await store.flush();

    expect(JSON.parse(await readFile(filePath, "utf8"))).toEqual({ count: 1 });
  });

  it("coalesces consecutive updates inside the debounce window", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-debounced-"));
    const filePath = path.join(root, "store.json");
    const store = new DebouncedJsonStore<{ count: number }>({
      filePath,
      fallback: { count: 0 },
      debounceMs: 20
    });

    await store.update((current) => ({ count: current.count + 1 }));
    await store.update((current) => ({ count: current.count + 1 }));
    await expect(stat(filePath)).rejects.toMatchObject({ code: "ENOENT" });

    await new Promise((resolve) => setTimeout(resolve, 80));

    expect(JSON.parse(await readFile(filePath, "utf8"))).toEqual({ count: 2 });
  });

  it("flushes before dispose and rejects updates after dispose", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-disposed-store-"));
    const filePath = path.join(root, "store.json");
    const store = new DebouncedJsonStore<{ count: number }>({
      filePath,
      fallback: { count: 0 }
    });

    await store.update((current) => ({ count: current.count + 1 }));
    await store.dispose();

    expect(JSON.parse(await readFile(filePath, "utf8"))).toEqual({ count: 1 });
    await expect(store.update((current) => current)).rejects.toMatchObject<Partial<LawchersError>>({
      code: "INVALID_INPUT",
      message: "store disposed"
    });
  });
});
