/**
 * 描述: migrate 命令实现
 * 主要功能:
 *     - 执行数据库 Schema 结构的初始化或升级迁移
 *     - 支持空运行模式 (dryRun)
 */

import { ok, fail, errorToResult } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import type { CliResult } from "../../../../src/foundation/index.js";

export interface MigrateArgs {
  dryRun?: boolean;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

export async function migrate(args: MigrateArgs): Promise<CliResult<Record<string, unknown>>> {
  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });

    const result: Record<string, unknown> = {
      dbPath: config.dbPath,
      home: config.home,
    };

    if (args.dryRun) {
      return ok({ ...result, dryRun: true, message: "Migration not executed (dry-run)" });
    }

    const db = createDatabase({ dbPath: config.dbPath });
    try {
      const beforeVersion = db.getSchemaVersion();
      db.migrate();
      const afterVersion = db.getSchemaVersion();

      return ok({
        ...result,
        beforeVersion,
        afterVersion,
        message: `Schema migrated from v${beforeVersion} to v${afterVersion}`,
      });
    } finally {
      db.close();
    }
  } catch (err) {
    return errorToResult(err);
  }
}
