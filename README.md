# lawchers-skills

本地优先的 Lawchers CLI 与 Agent Skills 工具集，为 Codex、OpenCode、Claude 等 Agent 提供轻量、确定性、JSON-first 的法律工作辅助能力。

当前版本只有一个正式命令入口：`lawchers`。功能不再拆成多个 npm package，而是作为 `packages/cli/skills/<skill-name>/scripts/` 下的 skill scripts 接入统一 CLI。

[快速开始](#快速开始) · [Agent Skills](#agent-skills) · [命令体系](#命令体系) · [项目结构](#项目结构) · [开发](#开发) · [安全边界](#安全边界)

## 为什么是 lawchers-skills？

- **Agent-Native Design** — Skill 写清楚“什么时候用、怎么用、不能做什么”，CLI 负责稳定执行。
- **Single CLI Entry** — 只有 `lawchers` 一个入口，避免每个功能重复实现 parser、JSON 输出、logger、doctor。
- **Skill Scripts** — 每个功能放在自己的 skill 目录里，说明文档和代码靠在一起，便于 Agent 读取和维护。
- **Local First** — 默认写本地 SQLite 或本地文件，不需要云服务、Obsidian、API key 才能启动。
- **JSON-First Output** — stdout 始终输出一行 JSON，适合 Agent 调用、测试和管道处理。
- **Small Surface** — 不引入 Commander/Yargs、Changesets、动态插件加载；先把核心链路做薄。

## 功能

| Skill | 状态 | 能力 |
| --- | --- | --- |
| `memory-tools` | 已接入 | 本地长期记忆：learn、recall、list、clear、doctor、migrate、Markdown export |
| `material-tools` | 规划中 | 本地文件、文件夹、归档解析，输出 Markdown/plain text/sections |
| `legal-kb` | 规划中 | 本地法律知识库 ingest/search/ask/docs/stats/doctor |
| `case-workbench` | 规划中 | 证据抽取、时间线、卷宗、案件工作台渲染 |
| `setup-lawchers-skills` | 占位 | 全局安装、初始化、doctor 工作流 |

## 快速开始

### Requirements

- Node.js `>=20`
- npm，版本由根 `package.json` 的 `packageManager` 锁定
- 首版不支持 Bun/Deno

### Install From Source

```bash
npm install
npm run build
npm link --workspace @lawchers/cli
```

### First Run

```bash
lawchers doctor
lawchers memory doctor
lawchers memory learn --user local --user-message "我喜欢轻量工具"
lawchers memory recall --user local --query "工具偏好"
```

如果没有 link，也可以从仓库根目录直接运行构建产物：

```bash
node packages/cli/dist/src/bin.js memory doctor
```

stdout 始终是一行 JSON：

```json
{"ok":true,"result":{},"warnings":[]}
```

## Quick Start For AI Agents

> Agent 操作本仓库时，应先读取 [CODEX.md](./CODEX.md)，再读取目标 skill 的 `SKILL.md`。

Step 1 — Build CLI:

```bash
npm install
npm run build
```

Step 2 — Verify environment:

```bash
node packages/cli/dist/src/bin.js doctor
```

Step 3 — Use memory:

```bash
node packages/cli/dist/src/bin.js memory recall --user local --query "<current task>"
node packages/cli/dist/src/bin.js memory learn --user local --user-message "<stable preference/fact/goal>"
```

Step 4 — Prefer skill guidance:

```text
packages/cli/skills/memory-tools/SKILL.md
```

## Agent Skills

| Skill | Description |
| --- | --- |
| `memory-tools` | Local long-term memory for durable user preferences, facts, and goals |
| `material-tools` | Future material parsing workflow |
| `legal-kb` | Future legal knowledge base workflow |
| `case-workbench` | Future evidence, timeline, dossier, and case workbench workflow |
| `setup-lawchers-skills` | Future setup and global doctor workflow |

Skills are repo-local until listed in `.claude-plugin/plugin.json`. Draft, personal, in-progress, and deprecated skills must not enter the manifest.

## 命令体系

### 1. Global Commands

```bash
lawchers doctor
```

`lawchers doctor` 聚合已注册 feature 的 doctor 结果。top-level `ok: true` 只表示 CLI 自身正常；模块状态在 `result.modules[].status` 中体现。

### 2. Domain Commands

```bash
lawchers memory doctor
lawchers memory migrate
lawchers memory learn --user <id> --user-message <text>
lawchers memory recall --user <id> --query <text>
lawchers memory list --user <id>
lawchers memory clear --user <id> --confirm
lawchers memory sync-obsidian --user <id> --out <folder>
```

### 3. Global Flags

```bash
--home <path>          # override LAWCHERS_HOME
--config-file <path>   # explicit config file
--log-level <level>    # error|warn|info|debug|trace
--trace-id <id>        # inject trace id into logger
```

## 项目结构

```text
packages/cli/
  src/                  # CLI kernel, parser, registry, doctor, JSON result handling
  src/foundation/       # config, result, errors, logger, provider helpers
  skills/
    memory-tools/
      SKILL.md
      scripts/
    material-tools/
      scripts/
    legal-kb/
      scripts/
    case-workbench/
      scripts/
```

重要文档：

- [CODEX.md](./CODEX.md)
- [CLI 契约](./docs/cli-contract.md)
- [配置说明](./docs/config.md)
- [数据布局](./docs/data-layout.md)
- [错误码](./docs/error-codes.md)
- [测试策略](./docs/testing.md)
- [Memory 使用说明](./docs/memory-cli.md)

## 数据与配置

默认 Lawchers home：

- explicit `--home`
- `LAWCHERS_HOME`
- Windows `%LOCALAPPDATA%/lawchers`
- macOS `~/Library/Application Support/lawchers`
- Linux/other `$XDG_DATA_HOME/lawchers`
- fallback `~/.local/share/lawchers`

Memory DB 默认位置：

```text
$LAWCHERS_HOME/memory/memory.db
```

不配置 Obsidian、embedding provider 或 API key 也能使用 memory。当前 recall 使用 recent + FTS5；embedding 只做 provider 状态诊断。

## 安全边界

- Bridge 只作为能力边界和测试场景参考，不复制 Bridge 运行时代码。
- stdout 只输出 JSON；stderr 只允许 JSON-lines logger。
- 日志不得包含 API key、完整文档正文或敏感用户内容。
- 写操作必须有明确确认或稳定错误。
- `dist/` 是本地构建产物，不提交。

## 开发

```bash
npm install
npm run lint
npm run typecheck
npm test
npm run build
```

测试和 fixtures 放在 `.local-tests/<project>/`，只用于本地开发并被 git 忽略。

## 当前状态

- `lawchers` 单入口已完成。
- `memory-tools` 已接入并本地验证。
- `material-tools`、`legal-kb`、`case-workbench` 只有目录和计划，业务 scripts 尚未实现。
- 不发布 npm 包，不提交 `dist/`。
