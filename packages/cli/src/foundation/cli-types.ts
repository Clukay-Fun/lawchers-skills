/**
 * 描述: 统一 CLI feature registry 类型定义
 * 主要功能:
 *     - 固定 feature、handler、context 和 doctor section 契约
 *     - 为 lawchers CLI 与业务模块提供无环依赖的共享类型
 */

import type { Readable } from "node:stream";
import type { LawchersConfig } from "./config.js";
import type { CliResult } from "./result.js";
import type { Logger, LogLevel } from "./logger.js";

export type ParsedFlagValue = string | boolean | undefined;

export interface ParsedArgs {
  domain?: string;
  command: string;
  flags: Record<string, ParsedFlagValue>;
  positionals: string[];
}

export interface GlobalFlags {
  home?: string;
  configFile?: string;
  logLevel: LogLevel;
  traceId?: string;
}

export interface CliContext {
  home: string;
  config: LawchersConfig;
  logger: Logger;
  signal: AbortSignal;
  stdin: Readable;
  env: Readonly<Record<string, string>>;
  globalFlags: GlobalFlags;
}

export interface DoctorSection {
  domain: string;
  status: "ok" | "degraded" | "error";
  details: Record<string, unknown>;
  warnings?: string[];
}

export interface CommandHandler {
  description: string;
  run(args: ParsedArgs, ctx: CliContext): Promise<CliResult<unknown>>;
}

export interface CommandFeature {
  domain: string;
  description: string;
  commands: Record<string, CommandHandler>;
  doctor?: (ctx: CliContext) => Promise<CliResult<DoctorSection>>;
}
