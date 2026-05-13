import { mkdtemp, mkdir, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LawchersError, loadConfig, resolveLawchersHome } from "../src/index.js";

describe("home resolution", () => {
  it("uses explicit home first", () => {
    expect(resolveLawchersHome({ home: "custom", env: { LAWCHERS_HOME: "/env" } })).toBe(
      path.resolve("custom")
    );
  });

  it("uses LAWCHERS_HOME before XDG_DATA_HOME", () => {
    expect(
      resolveLawchersHome({
        env: { LAWCHERS_HOME: "/lawchers", XDG_DATA_HOME: "/xdg" }
      })
    ).toBe("/lawchers");
  });

  it("uses XDG_DATA_HOME with lawchers suffix", () => {
    expect(resolveLawchersHome({ env: { XDG_DATA_HOME: "/xdg" }, platform: "linux" })).toBe("/xdg/lawchers");
  });

  it("uses platform defaults without creating the directory", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-home-"));
    const macPath = resolveLawchersHome({ env: {}, platform: "darwin", homeDir: root });
    const linuxPath = resolveLawchersHome({ env: {}, platform: "linux", homeDir: root });

    expect(macPath).toBe(path.join(root, "Library", "Application Support", "lawchers"));
    expect(linuxPath).toBe(path.join(root, ".local", "share", "lawchers"));
    await expect(stat(macPath)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(stat(linuxPath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("uses LOCALAPPDATA on Windows", () => {
    expect(
      resolveLawchersHome({
        env: { LOCALAPPDATA: "C:\\Users\\me\\AppData\\Local", XDG_DATA_HOME: "/xdg" },
        platform: "win32"
      })
    ).toBe(path.resolve("C:\\Users\\me\\AppData\\Local", "lawchers"));
  });
});

describe("config loading", () => {
  it("merges defaults, user config, project config, and overrides", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-config-"));
    const home = path.join(root, "home");
    const cwd = path.join(root, "project");
    await mkdir(home, { recursive: true });
    await mkdir(path.join(cwd, ".lawchers"), { recursive: true });
    await writeFile(
      path.join(home, "config.json"),
      JSON.stringify({ providers: { embedding: { model: "user-model", timeoutMs: 100 } } })
    );
    await writeFile(
      path.join(cwd, ".lawchers", "config.json"),
      JSON.stringify({ providers: { embedding: { model: "project-model" } } })
    );

    const loaded = await loadConfig({
      cwd,
      home,
      overrides: { providers: { embedding: { timeoutMs: 200 } } }
    });

    expect(loaded.config.providers.embedding).toMatchObject({
      type: "openai-compatible",
      model: "project-model",
      timeoutMs: 200
    });
  });

  it("deep merges objects, replaces arrays, ignores undefined, and keeps null overrides", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-merge-config-"));
    const home = path.join(root, "home");
    const cwd = path.join(root, "project");
    await mkdir(home, { recursive: true });
    await mkdir(path.join(cwd, ".lawchers"), { recursive: true });
    await writeFile(
      path.join(home, "config.json"),
      JSON.stringify({
        providers: {
          embedding: {
            headers: { a: "user", b: "user" },
            endpoints: ["user"],
            nullable: "user"
          }
        }
      })
    );
    await writeFile(
      path.join(cwd, ".lawchers", "config.json"),
      JSON.stringify({
        providers: {
          embedding: {
            headers: { b: "project" },
            endpoints: ["project"],
            nullable: null
          }
        }
      })
    );

    const loaded = await loadConfig({
      cwd,
      home,
      overrides: {
        providers: {
          embedding: {
            headers: { c: "override" },
            model: undefined
          }
        }
      }
    });

    expect(loaded.config.providers.embedding.headers).toEqual({
      a: "user",
      b: "project",
      c: "override"
    });
    expect(loaded.config.providers.embedding.endpoints).toEqual(["project"]);
    expect(loaded.config.providers.embedding.nullable).toBeNull();
    expect(loaded.config.providers.embedding.model).toBe("text-embedding-3-small");
  });

  it("throws CONFIG_INVALID for invalid JSON", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lawchers-invalid-config-"));
    const home = path.join(root, "home");
    await mkdir(home, { recursive: true });
    await writeFile(path.join(home, "config.json"), "{nope");

    await expect(loadConfig({ home })).rejects.toMatchObject<Partial<LawchersError>>({
      code: "CONFIG_INVALID"
    });
  });
});
