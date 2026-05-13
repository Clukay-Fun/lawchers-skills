/**
 * 描述: lawchers CLI 执行内核
 * 主要功能:
 *     - 构建 CliContext 并分发到 feature command
 *     - 统一 JSON stdout、退出码和 doctor 聚合语义
 */

import { Readable, Writable } from "node:stream";
import {
  createLogger,
  errorToResult,
  fail,
  loadConfig,
  ok,
  type CliContext,
  type CliResult,
  type CommandFeature,
  type DoctorSection,
  type ErrorCode,
} from "./foundation/index.js";
import { availableDomains, features, getFeature } from "./features.js";
import { parseCliInput } from "./parser.js";

export interface RunCliOptions {
  argv?: string[];
  env?: NodeJS.ProcessEnv;
  stdin?: Readable;
  stdout?: Writable;
  stderr?: Writable;
  signal?: AbortSignal;
}

export interface RunCliResult {
  exitCode: number;
  result: CliResult<unknown>;
}

const userErrorCodes = new Set<ErrorCode>(["INVALID_INPUT", "MISSING_FIELD", "CONFIG_INVALID"]);

export async function runCli(options: RunCliOptions = {}): Promise<RunCliResult> {
  const argv = options.argv ?? process.argv;
  const env = normalizeEnv(options.env ?? process.env);
  const stdout: Writable = options.stdout ?? process.stdout;
  const stderr: Writable = options.stderr ?? process.stderr;
  const stdin = options.stdin ?? process.stdin;
  const signal = options.signal ?? new AbortController().signal;

  try {
    const input = parseCliInput(argv);
    const loadedConfig = await loadConfig({
      home: input.globalFlags.home,
      configFile: input.globalFlags.configFile,
      env,
    });
    const logger = createLogger({
      pkg: "@lawchers/cli",
      level: input.globalFlags.logLevel,
      traceId: input.globalFlags.traceId,
      env,
      sink: (line) => stderr.write(`${line}\n`),
    });
    const ctx: CliContext = {
      home: loadedConfig.home,
      config: loadedConfig.config,
      logger,
      signal,
      stdin,
      env,
      globalFlags: input.globalFlags,
    };

    const result = await dispatch(input.parsedArgs.positionals, input.parsedArgs, ctx);
    writeJson(stdout, result);
    return { result, exitCode: exitCodeForResult(result) };
  } catch (error) {
    const result = errorToResult(error, env);
    writeJson(stdout, result);
    return { result, exitCode: result.code === "UNKNOWN" ? 70 : exitCodeForResult(result) };
  }
}

async function dispatch(
  positionals: string[],
  parsedArgs: ReturnType<typeof parseCliInput>["parsedArgs"],
  ctx: CliContext
): Promise<CliResult<unknown>> {
  if (positionals.length === 0) {
    return fail("INVALID_INPUT", "Missing domain or command", {
      availableDomains: availableDomainsWithDoctor(),
    });
  }

  if (positionals[0] === "doctor") {
    return runAggregateDoctor(ctx);
  }

  const domain = positionals[0] as string;
  const command = positionals[1];
  const feature = getFeature(domain);
  if (!feature) {
    return fail("INVALID_INPUT", `Unknown domain: ${domain}`, {
      domain,
      availableDomains: availableDomainsWithDoctor(),
    });
  }

  if (!command) {
    return fail("INVALID_INPUT", `Missing command for domain: ${domain}`, {
      domain,
      availableCommands: Object.keys(feature.commands),
    });
  }

  const handler = feature.commands[command];
  if (!handler) {
    return fail("INVALID_INPUT", `Unknown command: ${command}`, {
      domain,
      command,
      availableCommands: Object.keys(feature.commands),
    });
  }

  return handler.run({ ...parsedArgs, domain, command }, ctx);
}

async function runAggregateDoctor(ctx: CliContext): Promise<CliResult<Record<string, unknown>>> {
  const modules = await Promise.all(features.map((feature) => runFeatureDoctor(feature, ctx)));
  return ok({
    home: ctx.home,
    modules,
  });
}

async function runFeatureDoctor(feature: CommandFeature, ctx: CliContext): Promise<DoctorSection> {
  if (!feature.doctor) {
    return {
      domain: feature.domain,
      status: "degraded",
      details: { message: "doctor not implemented" },
    };
  }

  try {
    const result = await feature.doctor(ctx);
    if (result.ok) {
      return result.result;
    }

    return {
      domain: feature.domain,
      status: "error",
      details: {
        code: result.code,
        message: result.message,
        ...result.details,
      },
    };
  } catch (error) {
    return {
      domain: feature.domain,
      status: "error",
      details: {
        message: error instanceof Error ? error.message : String(error),
      },
    };
  }
}

function availableDomainsWithDoctor(): string[] {
  return ["doctor", ...availableDomains()];
}

export function exitCodeForResult(result: CliResult<unknown>): number {
  if (result.ok) {
    return 0;
  }

  return userErrorCodes.has(result.code) ? 2 : 1;
}

function writeJson(stdout: Writable, result: CliResult<unknown>): void {
  stdout.write(`${JSON.stringify(result)}\n`);
}

function normalizeEnv(env: NodeJS.ProcessEnv): Record<string, string> {
  const normalized: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (value !== undefined) {
      normalized[key] = value;
    }
  }

  return normalized;
}
