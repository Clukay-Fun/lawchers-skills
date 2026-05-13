import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@lawchers/shared-core": `${root}packages/shared-core/src/index.ts`,
      "@lawchers/local-store": `${root}packages/local-store/src/index.ts`,
      "@lawchers/embedding-provider": `${root}packages/embedding-provider/src/index.ts`
    }
  },
  test: {
    coverage: {
      reporter: ["text", "lcov"]
    },
    include: ["packages/*/tests/**/*.test.ts"]
  }
});
