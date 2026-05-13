/**
 * 描述: Vitest 本地测试配置
 * 主要功能:
 *     - 将旧包名和 @lawchers/cli 映射到合并后的源码入口
 *     - 从 .local-tests 目录发现本地开发测试
 */

import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@lawchers/shared-core": `${root}packages/cli/src/foundation/index.ts`,
      "@lawchers/embedding-provider": `${root}packages/cli/src/foundation/embedding-provider/index.ts`,
      "@lawchers/memory": `${root}packages/cli/skills/memory-tools/scripts/index.ts`,
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
