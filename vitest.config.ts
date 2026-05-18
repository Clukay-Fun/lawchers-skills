/**
 * 描述: Vitest 本地测试配置
 * 主要功能:
 *     - 将 @lawchers/cli 映射到源码入口
 *     - 从 .local-tests 目录发现本地开发测试
 */

import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@lawchers/cli": `${root}packages/cli/src/index.ts`
    }
  },
  test: {
    coverage: {
      reporter: ["text", "lcov"]
    },
    include: [".local-tests/**/*.test.ts"],
    passWithNoTests: true
  }
});
