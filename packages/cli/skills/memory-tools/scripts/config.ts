/**
 * 描述: 长期记忆模块配置管理
 * 主要功能:
 *     - 合并和加载来自多处 (User, Legacy, Project) 的配置文件
 *     - 提供记忆数据库路径、提取器参数等默认值与解析结果
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import { LawchersError, resolveLawchersHome, toLawchersError } from "../../../src/foundation/index.js";
import type { LoadConfigOptions } from "../../../src/foundation/index.js";

export interface MemoryConfig {
  dbPath?: string;
  extractor?: {
    type?: "rule" | "noop";
    confidenceThreshold?: number;
  };
}

export interface ResolvedMemoryConfig {
  dbPath: string;
  extractor: {
    type: "rule" | "noop";
    confidenceThreshold: number;
  };
  home: string;
}

interface RawConfig {
  memory?: Record<string, unknown>;
}

const defaultMemorySection: Record<string, unknown> = {
  extractor: {
    type: "rule",
    confidenceThreshold: 0.5,
  },
};

export async function createMemoryConfig(options: LoadConfigOptions = {}): Promise<ResolvedMemoryConfig> {
  const cwd = options.cwd ?? process.cwd();
  const home = resolveLawchersHome(options);
  const env = options.env ?? process.env;

  const paths = {
    userConfig: path.resolve(home, "config.json"),
    projectConfig: path.resolve(cwd, ".lawchers", "config.json"),
    configFile: options.configFile ? path.resolve(options.configFile) : undefined,
  };

  const userRaw = await readRawConfig(paths.userConfig);
  const projectRaw = await readRawConfig(paths.projectConfig);
  const explicitRaw = paths.configFile ? await readRequiredRawConfig(paths.configFile) : undefined;

  const merged = deepMerge(defaultMemorySection, userRaw?.memory, projectRaw?.memory, explicitRaw?.memory, options.overrides as Record<string, unknown> | undefined);

  const extractor = (merged.extractor ?? {}) as Record<string, unknown>;
  const memoryDbDir = path.resolve(home, "memory");

  return {
    dbPath: (merged.dbPath as string) ?? path.resolve(memoryDbDir, "memory.db"),
    extractor: {
      type: (extractor.type as "rule" | "noop") ?? "rule",
      confidenceThreshold: (extractor.confidenceThreshold as number) ?? 0.5,
    },
    home,
  };
}

async function readRequiredRawConfig(filePath: string): Promise<RawConfig> {
  const config = await readRawConfig(filePath);
  if (!config) {
    throw new LawchersError("IO_ERROR", `Config file does not exist: ${filePath}`, { path: filePath });
  }

  return config;
}

async function readRawConfig(filePath: string): Promise<RawConfig | undefined> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw) as RawConfig;
  } catch (error) {
    if (error instanceof LawchersError) throw error;
    const nodeError = error as NodeJS.ErrnoException;
    if (nodeError.code === "ENOENT") return undefined;
    if (error instanceof SyntaxError) {
      throw new LawchersError("CONFIG_INVALID", `Config file is not valid JSON: ${filePath}`, { path: filePath });
    }
    throw new LawchersError("IO_ERROR", `Failed to read config file: ${filePath}`, { path: filePath });
  }
}

function deepMerge(...sources: Array<Record<string, unknown> | undefined>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const source of sources) {
    if (!source) continue;
    for (const [key, value] of Object.entries(source)) {
      if (value === undefined) continue;
      if (Array.isArray(value) || value === null || typeof value !== "object") {
        result[key] = value;
      } else if (typeof result[key] === "object" && !Array.isArray(result[key]) && result[key] !== null) {
        result[key] = deepMerge(result[key] as Record<string, unknown>, value as Record<string, unknown>);
      } else {
        result[key] = structuredClone(value);
      }
    }
  }
  return result;
}
