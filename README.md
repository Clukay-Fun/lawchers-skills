# lawchers-skills

面向 AI 编码代理（Claude Code / Codex 等）的工具与 Skill 集合。每个子目录是一个**自包含、可独立安装使用**的项目，核心能力沉淀在 CLI 里，Skill/README 只是让代理能稳定调用的外壳。

## 子项目

| 项目 | 作用 | 状态 |
|------|------|------|
| [`legal-desensitizer/`](legal-desensitizer/) | **通用案件材料脱敏 skill**（通用核心 + 场景 profile）：对 `.txt / .md / .csv / .docx / .xlsx` 做**可逆脱敏、映射、还原、审计**，图片/扫描件走不可逆 OCR；profile 控制脱/留（`labor` 默认已验证、`strict` 全脱）。可选接入本地 NER；PDF 支持为 opt-in extra | 可用（劳动场景首轮验收） |

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
