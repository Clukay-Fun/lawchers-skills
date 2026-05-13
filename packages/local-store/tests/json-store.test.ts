import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LawchersError } from "@lawchers/shared-core";
import { readJsonFile, writeJsonFileAtomic } from "../src/index.js";

describe("json store", () => {
  it("returns fallback when the file is missing", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-json-"));
    await expect(readJsonFile(path.join(root, "missing.json"), { ok: true })).resolves.toEqual({
      ok: true
    });
  });

  it("writes JSON atomically", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-json-"));
    const filePath = path.join(root, "nested", "store.json");
    await writeJsonFileAtomic(filePath, { value: 42 });

    expect(JSON.parse(await readFile(filePath, "utf8"))).toEqual({ value: 42 });
  });

  it("reports invalid JSON", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-json-"));
    const filePath = path.join(root, "broken.json");
    await writeFile(filePath, "{nope");

    await expect(readJsonFile(filePath, {})).rejects.toMatchObject<Partial<LawchersError>>({
      code: "INVALID_INPUT"
    });
  });

  it("replaces an existing JSON file", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-json-"));
    const filePath = path.join(root, "store.json");
    await writeJsonFileAtomic(filePath, { value: 1 });
    await writeJsonFileAtomic(filePath, { value: 2 });

    expect(JSON.parse(await readFile(filePath, "utf8"))).toEqual({ value: 2 });
  });
});
