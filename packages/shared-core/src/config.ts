import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { LawchersError } from "./errors.js";

export interface ProviderConfig {
  type: string;
  baseUrl?: string;
  model?: string;
  apiKeyEnv?: string;
  timeoutMs?: number;
  [key: string]: unknown;
}

export interface LawchersConfig {
  providers: {
    embedding: ProviderConfig;
    ocr: ProviderConfig;
    rerank: ProviderConfig;
  };
}

export interface ResolveHomeOptions {
  home?: string;
  env?: NodeJS.ProcessEnv;
  platform?: NodeJS.Platform;
  homeDir?: string;
}

export interface LoadConfigOptions extends ResolveHomeOptions {
  cwd?: string;
  overrides?: PartialLawchersConfig;
}

export type PartialLawchersConfig = {
  providers?: {
    embedding?: Partial<ProviderConfig>;
    ocr?: Partial<ProviderConfig>;
    rerank?: Partial<ProviderConfig>;
  };
};

export interface LoadedConfig {
  config: LawchersConfig;
  home: string;
  paths: {
    projectConfig: string;
    userConfig: string;
    legacyUserConfig: string;
  };
}

const defaultConfig: LawchersConfig = {
  providers: {
    embedding: {
      type: "openai-compatible",
      baseUrl: "https://api.openai.com/v1",
      model: "text-embedding-3-small",
      apiKeyEnv: "OPENAI_API_KEY"
    },
    ocr: { type: "disabled" },
    rerank: { type: "disabled" }
  }
};

export function getDefaultConfig(): LawchersConfig {
  return mergeConfig(defaultConfig);
}

export function resolveLawchersHome(options: ResolveHomeOptions = {}): string {
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const homeDir = options.homeDir ?? os.homedir();

  if (options.home) {
    return path.resolve(options.home);
  }

  if (env.LAWCHERS_HOME) {
    return path.resolve(env.LAWCHERS_HOME);
  }

  if (platform === "win32" && env.LOCALAPPDATA) {
    return path.resolve(env.LOCALAPPDATA, "lawchers");
  }

  if (platform === "darwin") {
    return path.resolve(homeDir, "Library", "Application Support", "lawchers");
  }

  if (env.XDG_DATA_HOME) {
    return path.resolve(env.XDG_DATA_HOME, "lawchers");
  }

  return path.resolve(homeDir, ".local", "share", "lawchers");
}

export async function loadConfig(options: LoadConfigOptions = {}): Promise<LoadedConfig> {
  const cwd = options.cwd ?? process.cwd();
  const home = resolveLawchersHome(options);
  const paths = {
    projectConfig: path.resolve(cwd, ".lawchers", "config.json"),
    userConfig: path.resolve(home, "config.json"),
    legacyUserConfig: path.resolve(os.homedir(), ".lawchers", "config.json")
  };

  const userConfig = await readOptionalConfig(paths.userConfig);
  const legacyUserConfig = userConfig ? undefined : await readOptionalConfig(paths.legacyUserConfig);
  const projectConfig = await readOptionalConfig(paths.projectConfig);

  return {
    config: mergeConfig(defaultConfig, legacyUserConfig, userConfig, projectConfig, options.overrides),
    home,
    paths
  };
}

async function readOptionalConfig(filePath: string): Promise<PartialLawchersConfig | undefined> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw) as PartialLawchersConfig;
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") {
      return undefined;
    }

    if (error instanceof SyntaxError) {
      throw new LawchersError("CONFIG_INVALID", `Config file is not valid JSON: ${filePath}`, {
        path: filePath
      });
    }

    throw new LawchersError("IO_ERROR", `Failed to read config file: ${filePath}`, {
      path: filePath
    });
  }
}

function mergeConfig(...configs: Array<PartialLawchersConfig | undefined>): LawchersConfig {
  const merged = structuredClone(defaultConfig);

  for (const config of configs) {
    deepMergeInto(merged as unknown as Record<string, unknown>, config);
  }

  return merged;
}

function deepMergeInto(target: Record<string, unknown>, source: unknown): void {
  if (!isPlainObject(source)) {
    return;
  }

  for (const [key, value] of Object.entries(source)) {
    if (value === undefined) {
      continue;
    }

    if (Array.isArray(value) || value === null || !isPlainObject(value)) {
      target[key] = value;
      continue;
    }

    if (!isPlainObject(target[key])) {
      target[key] = {};
    }

    deepMergeInto(target[key] as Record<string, unknown>, value);
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
