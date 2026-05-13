# CODEX.md

本文件是 `lawchers-skills` 的根项目准则。Codex、OpenCode、Claude 或其他 Agent 在本仓库工作前，应优先读取并遵守这里的规则。

## 当前方向

- 项目目标是轻便、可维护、Agent 友好的本地工具体系。
- 不把每个功能都做成一套完整独立 CLI；优先建设统一的 `lawchers` 地基 CLI，再让 memory、material、legal-kb、case-workbench 作为功能模块扩展。
- Skill 负责告诉 Agent 什么时候调用、如何调用、有哪些安全边界；CLI 负责确定性执行、JSON 输出、本地文件和数据库操作。
- Bridge 仅作为能力边界、数据结构、产品体验、命令接口和测试场景参考，不复制 Bridge 运行时代码、会话管理、卡片模板、队列调度、回调机制或平台适配器。

## 架构准则

- 通用契约、本地持久化和 provider 底座都内置在 `packages/cli/src/foundation/`。
- 功能代码放在对应 skill 的 `scripts/` 目录下，例如 `packages/cli/skills/memory-tools/scripts/`。
- 模型和外部服务适配放在明确的 foundation provider 模块后面。
- 聚合 CLI 只做命令注册、参数解析、JSON 输出、错误处理、config/logger/doctor 等横向能力，不放业务逻辑。
- 业务脚本只暴露公开 command registry，不跨目录 import 未从 foundation 或自身 `index.ts` 暴露的内部文件。
- 不让一个业务功能依赖另一个业务功能的内部状态文件。

## CLI 准则

- stdout 必须保持可解析 JSON。
- stderr 日志必须是 JSON-lines。
- 错误码复用 `shared-core` 的 `ErrorCode`，新增错误码必须先改 `shared-core` 和文档。
- destructive 或不可逆命令必须有显式确认参数。
- 缺少参数、低置信度、配置错误、provider 不可用都要返回稳定错误结构。
- 默认优先本地、确定性、无后台服务；只有用户明确配置时才访问外部 provider。

## Skill 准则

- Skill 只写 Agent 使用说明、路由规则、输入输出约束和安全边界，不隐藏业务状态。
- Skill 应调用统一入口 `lawchers <domain> <command>`。
- repo-local skill 不应再推荐独立业务 CLI 命令。
- 已发布 skill 必须说明：主命令、输入、JSON 输出、常见错误码、低置信度处理、配置失败处理和 fallback 行为。
- 草稿、开发中、个人使用或废弃 skill 不得进入 `.claude-plugin/plugin.json`。

## 文件与注释准则

- 所有代码文件必须有文件头注释。
- 头注释采用当前 `memory-cli` 风格，至少包含：

```ts
/**
 * 描述: 这个文件负责什么
 * 主要功能:
 *     - 关键职责一
 *     - 关键职责二
 */
```

- 头注释要说明职责，不写空泛套话。
- 文件内部注释按必要性添加：复杂流程、边界处理、安全判断、跨平台兼容、非显然业务规则需要注释；简单赋值和显然代码不需要注释。
- 新增代码优先保持 ASCII；已有中文注释文件可以继续使用中文注释。
- 不把临时任务笔记、个人偏好、未验证猜测写进长期文档或源码注释。

## 数据与安全

- 本地绝对路径视为用户显式提供的材料，但使用前仍要验证存在性、类型和边界。
- archive 解压必须防 zip-slip，并限制大小、数量、类型和嵌套层级。
- OCR、parser、provider 调用必须有 timeout。
- 日志不得包含 API key、完整文档正文、敏感用户内容或大段原文。
- SQLite 使用 WAL、transaction 和 busy timeout。
- JSON store 使用文件锁与 atomic write。

## 测试与验证

- 当前测试和夹具放在 `.local-tests/<project>/`，只用于本地开发并被 git 忽略。
- 修改 CLI 输出、config、数据布局、错误码、安全边界或测试策略时，同步更新相关文档。
- 验证从最窄相关检查开始，按风险扩大：

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

- 需要 provider secrets 的测试必须与默认本地测试分离。

## Git 准则

- 编辑前查看 `git status --short`。
- 不回滚用户已有改动。
- 保持一次变更一个清晰主题。
- 不把 cleanup、文档搬迁、重构和行为修改混在一起，除非计划明确要求。
- 交付时说明实际跑过的命令；没跑的检查要说明原因。
