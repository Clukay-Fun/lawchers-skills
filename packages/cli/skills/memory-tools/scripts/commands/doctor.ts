/**
 * 描述: doctor 命令实现
 * 主要功能:
 *     - 诊断当前的系统环境和依赖状态
 *     - 检查数据库状态、Extractor 配置及 Embedding 模型可用性
 */

import { ok, fail, errorToResult } from "../../../../src/foundation/index.js";
import { loadConfig } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase, type Database } from "../db.js";
import { createExtractor } from "../extractor.js";
import { checkEmbeddingProviderStatus } from "../provider-status.js";
import type { CliResult } from "../../../../src/foundation/index.js";

export interface DoctorArgs {
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

export async function doctor(args: DoctorArgs): Promise<CliResult<Record<string, unknown>>> {
  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });

    let db: Database | null = null;
    let dbStatus = "ok";
    let dbDetail: Record<string, unknown> = {};

    try {
      db = createDatabase({ dbPath: config.dbPath });
      const schemaVersion = db.getSchemaVersion();
      dbDetail.schemaVersion = schemaVersion;
      dbDetail.ftsAvailable = db.isFtsAvailable();
      dbStatus = schemaVersion >= 1 ? "ok" : "uninitialized";
    } catch (err) {
      dbStatus = "error";
      dbDetail.error = err instanceof Error ? err.message : String(err);
    } finally {
      if (db) db.close();
    }

    let extractorStatus = "ok";
    try {
      createExtractor(config.extractor);
    } catch {
      extractorStatus = "error";
    }

    const loadedConfig = await loadConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const embedding = checkEmbeddingProviderStatus(loadedConfig.config.providers.embedding, args.env);

    const result: Record<string, unknown> = {
      home: config.home,
      dbPath: config.dbPath,
      db: { status: dbStatus, ...dbDetail },
      extractor: { type: config.extractor.type, threshold: config.extractor.confidenceThreshold, status: extractorStatus },
      embedding: { status: embedding.status, ...embedding.detail },
    };

    return ok(result);
  } catch (err) {
    return errorToResult(err);
  }
}
