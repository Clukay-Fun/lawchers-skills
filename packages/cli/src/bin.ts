#!/usr/bin/env node

/**
 * 描述: lawchers CLI 可执行入口
 * 主要功能:
 *     - 调用统一 CLI 执行内核
 *     - 根据标准退出码结束进程
 */

import { runCli } from "./run.js";

runCli()
  .then(({ exitCode }) => {
    process.exit(exitCode);
  })
  .catch((error) => {
    process.stdout.write(JSON.stringify({
      ok: false,
      code: "UNKNOWN",
      message: error instanceof Error ? error.message : "Unexpected error",
      details: {},
    }) + "\n");
    process.exit(70);
  });
