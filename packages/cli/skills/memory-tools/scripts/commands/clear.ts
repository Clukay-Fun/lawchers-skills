/**
 * 描述: clear 命令实现
 * 主要功能:
 *     - 执行清空当前用户所有记忆数据的操作
 *     - 需要确认标志 (--confirm) 以防止误删
 */

import { ok, fail, errorToResult } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import type { CliResult } from "../../../../src/foundation/index.js";

export interface ClearArgs {
  user?: string;
  confirm?: boolean;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

export async function clear(args: ClearArgs): Promise<CliResult<Record<string, unknown>>> {
  if (!args.user) {
    return fail("MISSING_FIELD", "Missing required field: --user", { field: "user" });
  }
  if (!args.confirm) {
    return fail("INVALID_INPUT", "Clear requires --confirm flag", { field: "confirm" });
  }

  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const db = createDatabase({ dbPath: config.dbPath });

    try {
      db.migrate();
      db.deleteMemories(args.user);
      return ok({ user: args.user, cleared: true });
    } finally {
      db.close();
    }
  } catch (err) {
    return errorToResult(err);
  }
}
