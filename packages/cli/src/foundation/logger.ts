/**
 * 描述: 结构化日志工具
 * 主要功能:
 *     - 输出固定字段的 stderr JSON-lines 日志
 *     - 注入 pkg、event、level、traceId 与 details 信息
 */

export type LogLevel = "error" | "warn" | "info" | "debug" | "trace";

export interface LoggerOptions {
  level?: LogLevel;
  traceId?: string;
  env?: NodeJS.ProcessEnv;
  pkg: string;
  sink?: (line: string) => void;
  now?: () => Date;
}

export interface Logger {
  error(event: string, message: string, fields?: Record<string, unknown>): void;
  warn(event: string, message: string, fields?: Record<string, unknown>): void;
  info(event: string, message: string, fields?: Record<string, unknown>): void;
  debug(event: string, message: string, fields?: Record<string, unknown>): void;
  trace(event: string, message: string, fields?: Record<string, unknown>): void;
}

const levelWeights: Record<LogLevel, number> = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3,
  trace: 4
};

export function createLogger(options: LoggerOptions): Logger {
  const minLevel = options.level ?? "info";
  const sink = options.sink ?? ((line: string) => process.stderr.write(`${line}\n`));
  const now = options.now ?? (() => new Date());
  const env = options.env ?? process.env;
  const traceId = options.traceId ?? env.LAWCHERS_TRACE_ID;

  function write(level: LogLevel, event: string, message: string, fields: Record<string, unknown> = {}) {
    if (levelWeights[level] > levelWeights[minLevel]) {
      return;
    }

    const line: Record<string, unknown> = {
      ts: now().toISOString(),
      level,
      msg: message,
      pkg: options.pkg,
      event
    };

    if (traceId) {
      line.traceId = traceId;
    }

    if (Object.keys(fields).length > 0) {
      line.details = fields;
    }

    sink(JSON.stringify(line));
  }

  return {
    error: (event, message, fields) => write("error", event, message, fields),
    warn: (event, message, fields) => write("warn", event, message, fields),
    info: (event, message, fields) => write("info", event, message, fields),
    debug: (event, message, fields) => write("debug", event, message, fields),
    trace: (event, message, fields) => write("trace", event, message, fields)
  };
}
