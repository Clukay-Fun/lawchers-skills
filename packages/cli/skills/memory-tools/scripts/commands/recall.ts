/**
 * 描述: recall 命令实现
 * 主要功能:
 *     - 根据用户的查询语句，结合最近记忆与 FTS 搜索召回相关记忆内容
 *     - 格式化输出召回的内容以便 Agent 获取并参考
 */

import { ok, fail, errorToResult, loadConfig } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import { checkEmbeddingProviderStatus, embeddingStatusWarning } from "../provider-status.js";
import type { CliResult } from "../../../../src/foundation/index.js";
import type { Memory } from "../db.js";

export interface RecallArgs {
  user?: string;
  query?: string;
  limit?: number;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

function buildRecallBlock(memories: Memory[]): string {
  if (memories.length === 0) return "";
  const lines = memories.map(
    (m) => `- [${m.type}] ${m.content} (confidence: ${m.confidence.toFixed(2)})`
  );
  return `Relevant user memories:\n${lines.join("\n")}`;
}

export async function recall(args: RecallArgs): Promise<CliResult<Record<string, unknown>>> {
  if (!args.user) {
    return fail("MISSING_FIELD", "Missing required field: --user", { field: "user" });
  }
  if (!args.query) {
    return fail("MISSING_FIELD", "Missing required field: --query", { field: "query" });
  }

  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const db = createDatabase({ dbPath: config.dbPath });
    const warnings: string[] = [];

    try {
      const loadedConfig = await loadConfig({ home: args.home, configFile: args.configFile, env: args.env });
      const warning = embeddingStatusWarning(checkEmbeddingProviderStatus(loadedConfig.config.providers.embedding, args.env));
      if (warning) {
        warnings.push(warning);
      }

      db.migrate();
      const limit = args.limit ?? 5;

      const recent = db.recallRecent(args.user, limit);
      const fts = db.recallFts(args.user, args.query, limit);

      const seen = new Set<string>();
      const merged: Memory[] = [];
      for (const m of [...recent, ...fts]) {
        if (!seen.has(m.id)) {
          seen.add(m.id);
          merged.push(m);
        }
      }

      merged.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      const memories = merged.slice(0, limit);
      const recallBlock = buildRecallBlock(memories);

      return ok({ memories, recallBlock }, warnings);
    } finally {
      db.close();
    }
  } catch (err) {
    return errorToResult(err);
  }
}
