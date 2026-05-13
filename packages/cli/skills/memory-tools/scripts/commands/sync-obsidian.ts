/**
 * 描述: sync-obsidian 命令实现
 * 主要功能:
 *     - 导出指定用户的所有记忆并以 Markdown 格式保存到 Obsidian 文件夹中
 */

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { ok, fail, errorToResult } from "../../../../src/foundation/index.js";
import { createMemoryConfig } from "../config.js";
import { createDatabase } from "../db.js";
import type { CliResult } from "../../../../src/foundation/index.js";
import type { Memory } from "../db.js";

export interface SyncObsidianArgs {
  user?: string;
  out?: string;
  home?: string;
  configFile?: string;
  env?: NodeJS.ProcessEnv;
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\-.@]/g, "_");
}

export async function syncObsidian(args: SyncObsidianArgs): Promise<CliResult<Record<string, unknown>>> {
  if (!args.user) {
    return fail("MISSING_FIELD", "Missing required field: --user", { field: "user" });
  }
  if (!args.out) {
    return fail("MISSING_FIELD", "Missing required field: --out", { field: "out" });
  }

  const safeUser = sanitizeFilename(args.user);
  const resolvedOut = path.resolve(args.out);
  const filePath = path.resolve(resolvedOut, `${safeUser}.memory.md`);

  if (!filePath.startsWith(resolvedOut + path.sep)) {
    return fail("INVALID_INPUT", "Output path traversal detected", { user: args.user, out: args.out });
  }

  try {
    const config = await createMemoryConfig({ home: args.home, configFile: args.configFile, env: args.env });
    const db = createDatabase({ dbPath: config.dbPath });

    try {
      db.migrate();
      const allMemories = db.listMemories(args.user, 10000);

      const lines = allMemories.map((m: Memory) => {
        const tags = `#memory #${m.type}`;
        return `- **${m.type}**: ${m.content} ${tags}  \n  confidence: ${m.confidence.toFixed(2)}, created: ${m.createdAt}`;
      });

      const content = `# ${safeUser} - Memory Export\n\n${lines.join("\n")}\n`;

      mkdirSync(resolvedOut, { recursive: true });
      writeFileSync(filePath, content, "utf8");

      return ok({ user: args.user, safeUser, exportedTo: filePath, memoryCount: allMemories.length });
    } finally {
      db.close();
    }
  } catch (err) {
    return errorToResult(err);
  }
}
