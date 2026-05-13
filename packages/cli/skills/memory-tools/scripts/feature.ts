/**
 * 描述: memory 功能模块的 lawchers CLI 注册表
 * 主要功能:
 *     - 将 memory 业务命令暴露给统一 lawchers CLI
 *     - 从 CliContext 传递 home、config-file 和 env 等公共依赖
 */

import type { CommandFeature, CommandHandler, CliContext, ParsedArgs, DoctorSection, CliResult } from "../../../src/foundation/index.js";
import { ok } from "../../../src/foundation/index.js";
import { clear } from "./commands/clear.js";
import { doctor } from "./commands/doctor.js";
import { learn } from "./commands/learn.js";
import { list } from "./commands/list.js";
import { migrate } from "./commands/migrate.js";
import { recall } from "./commands/recall.js";
import { syncObsidian } from "./commands/sync-obsidian.js";

function flagString(args: ParsedArgs, name: string): string | undefined {
  const value = args.flags[name];
  return typeof value === "string" ? value : undefined;
}

function flagNumber(args: ParsedArgs, name: string): number | undefined {
  const value = args.flags[name];
  if (typeof value !== "string") {
    return undefined;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function flagBoolean(args: ParsedArgs, name: string): boolean {
  return args.flags[name] === true;
}

function command(description: string, run: CommandHandler["run"]): CommandHandler {
  return { description, run };
}

function common(ctx: CliContext) {
  return {
    home: ctx.home,
    configFile: ctx.globalFlags.configFile,
    env: ctx.env,
  };
}

async function runMemoryDoctor(ctx: CliContext): Promise<CliResult<DoctorSection>> {
  const result = await doctor(common(ctx));
  if (!result.ok) {
    return result;
  }

  const details = result.result;
  const embedding = details.embedding as Record<string, unknown> | undefined;
  const db = details.db as Record<string, unknown> | undefined;
  const status = db?.status === "error"
    ? "error"
    : embedding?.status && embedding.status !== "ok"
      ? "degraded"
      : "ok";

  return ok({
    domain: "memory",
    status,
    details,
    warnings: status === "degraded" ? ["memory provider fallback active"] : undefined,
  });
}

export const memoryFeature: CommandFeature = {
  domain: "memory",
  description: "Local long-term memory commands",
  commands: {
    doctor: command("Diagnose memory storage, extractor, and provider status", async (_args, ctx) => {
      return doctor(common(ctx));
    }),
    migrate: command("Create or upgrade the memory database schema", async (args, ctx) => {
      return migrate({ ...common(ctx), dryRun: flagBoolean(args, "dry-run") });
    }),
    learn: command("Persist a conversation and extract durable memories", async (args, ctx) => {
      return learn({
        ...common(ctx),
        user: flagString(args, "user"),
        userMessage: flagString(args, "user-message"),
        assistantMessage: flagString(args, "assistant-message"),
      });
    }),
    recall: command("Recall relevant memories for a query", async (args, ctx) => {
      return recall({
        ...common(ctx),
        user: flagString(args, "user"),
        query: flagString(args, "query"),
        limit: flagNumber(args, "limit"),
      });
    }),
    list: command("List stored memories for a user", async (args, ctx) => {
      return list({
        ...common(ctx),
        user: flagString(args, "user"),
        limit: flagNumber(args, "limit"),
      });
    }),
    clear: command("Clear all memories for a user after confirmation", async (args, ctx) => {
      return clear({
        ...common(ctx),
        user: flagString(args, "user"),
        confirm: flagBoolean(args, "confirm"),
      });
    }),
    "sync-obsidian": command("Export user memories to an Obsidian-compatible Markdown file", async (args, ctx) => {
      return syncObsidian({
        ...common(ctx),
        user: flagString(args, "user"),
        out: flagString(args, "out"),
      });
    }),
  },
  doctor: runMemoryDoctor,
};
