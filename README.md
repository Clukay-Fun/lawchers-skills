# lawchers-skills

面向 AI 编码代理（Claude Code / Codex 等）的工具与 Skill 集合。每个子目录是一个**自包含、可独立安装使用**的项目，核心能力沉淀在 CLI 里，Skill/README 只是让代理能稳定调用的外壳。

## 子项目

| 项目 | 作用 | 状态 |
|------|------|------|
| [`legal-desensitizer/`](legal-desensitizer/) | 文档脱敏 CLI：对 `.txt / .md / .csv / .docx / .xlsx` 做**可逆脱敏、映射、还原、审计**，可选接入本地 NER 模型；图片/扫描件走不可逆 OCR 派生（可选 `[ocr]` extra）。commercial-safe，不含 AGPL 依赖 | 可用（见项目 README） |

## 给 AI 代理的快速入口

如果你是被发来这个仓库链接的代理，想直接安装并使用某个能力：

1. 进入对应子目录，**先读它的 `README.md`**（安装/使用/安全约定都在那里）。
2. 子目录里的 `SKILL.md` / `AGENTS.md` / `CLAUDE.md` 是给代理的调用规范与边界，使用前必读。
3. 按 README 的"安装—自测—使用"三步走；自测（`pytest`）通过再处理真实文档。

例如脱敏能力：

```bash
cd legal-desensitizer
# 按该目录 README 安装、跑 pytest 自测、再 redact 真实文档
```

## 设计纪律（所有子项目共用）

- **CLI 是唯一能力核心**；Skill/README/未来的 MCP 都只是调用外壳。
- **可逆性靠位置映射**，不靠字符串替换。
- **SHA-256 防错配**：还原前校验脱敏文件，错配即报错不强行还原。
- **可逆 / 不可逆两类能力分清**：txt/md/csv/docx/xlsx 可逆；OCR/parse 派生不可逆（`restore_supported:false`、`best_effort`），不混为一谈。
- **commercial-safe**：默认栈不含 AGPL 或商用限制依赖（PyMuPDF 已移除），不用云 API。
- **不静默降级**：能力缺失（如模型/`[ocr]` extra 未装）时明确报错，不假装成功。

## 仓库约定

- **`docs/` 不进 git**：通用开发须知 `docs/HANDOFF.md` 与各项目 `docs/plan/00X-*.md` 阶段计划只在本地保留，不上传。代理派工时由人工指向对应文档。
- 生成产物（脱敏文件、map、audit）、模型文件、`tmp/` 不进 git。
- 提交、分支、合并等 git 操作一律人工处理；开发代理只改工作区、不碰 git。
