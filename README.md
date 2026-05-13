# lawchers-skills

`lawchers-skills` 是一个 monorepo，提供可复用的 Agent 技能与本地 CLI 工具，覆盖文档处理、长期记忆、法律知识库和案件工作台等工作流。

Phase 1 底座已合并进统一入口 `@lawchers/cli`。第一个功能 `memory-tools` 已通过 `lawchers memory ...` 接入；素材、法律知识库和案件工作台脚本尚未开始。

## 项目定位

本项目将为 Codex、Claude、OpenCode 等 Agent 构建一套 `技能 + CLI` 能力体系，供 Agent 直接调用：

```text
agent / codex / opencode
  -> skill: 意图路由、使用策略、提示词约束
  -> cli: 确定性执行、本地文件/数据库操作、JSON 输出
  -> providers/storage: 本地文件、SQLite、向量嵌入、Obsidian
```

Bridge 仅作为能力边界、数据结构、产品体验、命令接口和测试场景的参考。本仓库**不得**复制 Bridge 的运行时代码、会话管理、卡片模板、队列调度、回调机制或平台适配器。

## 首批项目

首轮实现分为五个项目计划：

1. [CLI 底座 / 嵌入向量提供者](./docs/projects/01-shared-core-local-store-embedding-provider.md)
2. [记忆 CLI](./docs/projects/02-memory-cli.md)
3. [素材工具](./docs/projects/03-material-cli.md)
4. [法律知识库](./docs/projects/04-kb-cli.md)
5. [案件工作台](./docs/projects/05-workbench-cli.md)

## 仓库结构

- `packages/cli/`：唯一 npm workspace 包，提供 `lawchers` 命令入口。
- `packages/cli/src/`：CLI kernel、registry、doctor 聚合、JSON 输出、退出码。
- `packages/cli/src/foundation/`：结果协议、配置、错误、日志、本地存储、embedding provider 等通用底座。
- `packages/cli/skills/memory-tools/`：长期记忆 skill 与 scripts。
- `packages/cli/skills/material-tools/`：未来素材解析 skill。
- `packages/cli/skills/legal-kb/`：未来法律知识库 skill。
- `packages/cli/skills/case-workbench/`：未来案件工作台 skill。
- `docs/`：接口契约、开发规范、测试策略和项目计划。

## 技能归属

技能与其调用的 CLI 包共置于同一目录：

- `packages/cli/skills/setup-lawchers-skills/`：初始化与全局诊断工作流。
- `packages/cli/skills/material-tools/`：素材解析工作流。
- `packages/cli/skills/memory-tools/`：长期记忆工作流。
- `packages/cli/skills/legal-kb/`：法律知识库工作流。
- `packages/cli/skills/case-workbench/`：证据、时间线、卷宗与案件工作台工作流。

这种组织方式将每个技能的使用说明和功能脚本约束在同一个 skill 边界内，避免为每个功能创建独立 package。

## 规划文档

- [项目准则](./CODEX.md)
- [路线图](./docs/roadmap.md)
- [开发规范](./docs/development-guidelines.md)
- [CLI 契约](./docs/cli-contract.md)
- [配置说明](./docs/config.md)
- [数据布局](./docs/data-layout.md)
- [错误码](./docs/error-codes.md)
- [安全策略](./docs/security.md)
- [测试策略](./docs/testing.md)
- [记忆 CLI 使用说明](./docs/memory-cli.md)

## 记忆模块快速开始

`lawchers memory` 是本地优先的长期记忆模块。即使没有配置 Obsidian、embedding provider 或模型密钥，也可以直接把记忆写入本地 SQLite，并通过最近记忆 + FTS5 关键词检索召回。

```bash
npm install
npm run build
npm link --workspace @lawchers/cli
lawchers memory doctor
lawchers memory learn --user local --user-message "我喜欢轻量工具"
lawchers memory recall --user local --query "工具偏好"
```

本地开发时也可以直接运行构建后的入口：

```bash
node packages/cli/dist/src/bin.js
```

stdout 始终是一行 JSON。macOS 默认数据位置是 `~/Library/Application Support/lawchers/memory/memory.db`。可用每条命令的 `--home <path>` 或全局环境变量 `LAWCHERS_HOME` 覆盖。

## 运行时要求

Phase 1 支持 Node.js `>=20`，使用 npm 作为包管理器。包管理器锁定在 `package.json` 中。

首个版本**不支持** Bun 和 Deno。

## 发布规则

任何技能在以下两处均完成注册前，不视为正式发布：

- `README.md`
- `.claude-plugin/plugin.json`

草稿、个人使用、开发中以及已弃用的技能**不得**出现在插件清单中。Phase 1 期间，仓库保留一个空的 `.claude-plugin/plugin.json` 清单文件，暂不发布任何技能。

## 开发命令

```bash
npm install
npm run typecheck
npm test
npm run build
```

测试与夹具统一放在 `.local-tests/<project>/` 下，仅用于本地开发，已被 git 忽略。`dist/` 是本地构建产物，不提交。
