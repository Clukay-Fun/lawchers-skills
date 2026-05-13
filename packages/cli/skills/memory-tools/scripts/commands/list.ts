/**
 * 描述: list 命令实现
 * 主要功能:
 *     - 查询并列出特定用户在系统中的最近长期记忆列表
 */

import { ok, fail, errorToResult } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import type { CliResult } from "../../../../src/foundation/index.js";
import type { Memory } from "../db.js";

export interface ListArgs {
  user?: string;
  limit?: number;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

export async function list(args: ListArgs): Promise<CliResult<{ memories: Memory[] }>> {
  if (!args.user) {
    return fail("MISSING_FIELD", "Missing required field: --user", { field: "user" });
  }

  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const db = createDatabase({ dbPath: config.dbPath });

    try {
      db.migrate();
      const limit = args.limit ?? 50;
      const memories = db.listMemories(args.user, limit);
      return ok({ memories });
    } finally {
      db.close();
    }
  } catch (err) {
    return errorToResult(err);
  }
}
