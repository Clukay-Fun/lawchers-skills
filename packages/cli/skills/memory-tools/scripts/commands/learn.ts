/**
 * 描述: learn 命令实现
 * 主要功能:
 *     - 接收用户与助手的对话信息并将其持久化到会话库
 *     - 调用提取器提取对话中的记忆价值点，并记录到长期记忆库中
 */

import { ok, fail, errorToResult, LawchersError } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import { createExtractor } from "../extractor.js";
import type { CliResult } from "../../../../src/foundation/index.js";

export interface LearnArgs {
  user?: string;
  userMessage?: string;
  assistantMessage?: string;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

export async function learn(args: LearnArgs): Promise<CliResult<Record<string, unknown>>> {
  if (!args.user) {
    return fail("MISSING_FIELD", "Missing required field: --user", { field: "user" });
  }
  if (!args.userMessage) {
    return fail("MISSING_FIELD", "Missing required field: --user-message", { field: "userMessage" });
  }

  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const extractor = createExtractor(config.extractor);
    const db = createDatabase({ dbPath: config.dbPath });

    try {
      db.migrate();
      const conversation = db.insertConversation({
        userId: args.user,
        userMessage: args.userMessage,
        assistantMessage: args.assistantMessage ?? null,
      });

      const candidates = extractor.extract(args.userMessage, args.assistantMessage ?? null);
      let writtenCount = 0;
      let skippedCount = 0;
      const items: Array<{ type: string; content: string; confidence: number; status: string; id?: string }> = [];

      for (const candidate of candidates) {
        const mem = db.insertMemory({
          userId: args.user,
          type: candidate.type,
          content: candidate.content,
          confidence: candidate.confidence,
          reason: candidate.reason,
          rawSpanStart: candidate.rawSpanStart ?? null,
          rawSpanEnd: candidate.rawSpanEnd ?? null,
          extractorName: extractor.name,
          extractorVersion: extractor.version,
          sourceConversationId: conversation.id,
        });

        items.push({
          type: candidate.type,
          content: candidate.content,
          confidence: candidate.confidence,
          status: mem.status,
          id: mem.id,
        });

        if (mem.status === "written") {
          writtenCount++;
        } else {
          skippedCount++;
        }
      }

      return ok({
        extractorName: extractor.name,
        writtenCount,
        skippedCount,
        items,
      });
    } finally {
      db.close();
    }
  } catch (err) {
    if (err instanceof LawchersError && err.code === "CONFIG_INVALID") {
      return fail("CONFIG_INVALID", err.message);
    }
    return errorToResult(err);
  }
}
