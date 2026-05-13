/**
 * 描述: lawchers 命令行参数解析器
 * 主要功能:
 *     - 解析 domain、command、positionals 和 --flag 参数
 *     - 将全局 flag 规范化为 CliContext 可用的结构
 */

import type { GlobalFlags, LogLevel, ParsedArgs, ParsedFlagValue } from "./foundation/index.js";

export interface ParsedCliInput {
  parsedArgs: ParsedArgs;
  globalFlags: GlobalFlags;
}

const logLevels = new Set<LogLevel>(["error", "warn", "info", "debug", "trace"]);

export function parseCliInput(argv: string[]): ParsedCliInput {
  const flags: Record<string, ParsedFlagValue> = {};
  const positionals: string[] = [];

  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i] as string;
    if (!token.startsWith("--")) {
      positionals.push(token);
      continue;
    }

    const rawKey = token.slice(2);
    const eqIndex = rawKey.indexOf("=");
    if (eqIndex !== -1) {
      const name = rawKey.slice(0, eqIndex);
      flags[name] = rawKey.slice(eqIndex + 1);
      continue;
    }

    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      flags[rawKey] = next;
      i += 1;
    } else {
      flags[rawKey] = true;
    }
  }

  const domain = positionals[0];
  const command = positionals[1] ?? domain ?? "";
  const parsedArgs: ParsedArgs = {
    domain,
    command,
    flags,
    positionals,
  };

  return {
    parsedArgs,
    globalFlags: {
      home: flagString(flags, "home"),
      configFile: flagString(flags, "config-file"),
      logLevel: parseLogLevel(flagString(flags, "log-level")),
      traceId: flagString(flags, "trace-id"),
    },
  };
}

function flagString(flags: Record<string, ParsedFlagValue>, name: string): string | undefined {
  const value = flags[name];
  return typeof value === "string" ? value : undefined;
}

function parseLogLevel(value: string | undefined): LogLevel {
  if (value && logLevels.has(value as LogLevel)) {
    return value as LogLevel;
  }

  return "info";
}
