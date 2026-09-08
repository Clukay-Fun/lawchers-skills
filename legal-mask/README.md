# 材料脱敏（legal-mask）

**通用中文案件材料脱敏 skill + CLI**。核心能力在 `legal-desens` CLI；`SKILL.md` 让模型按**用途**（内部分析 / 对外发送）而不是文件扩展名决定 profile 与流程。

- 命令：`legal-desens`（不在 PATH 时用 `python3 -m legal_desens.cli`）
- 默认栈 commercial-safe，无 AGPL；`[pdf]` extra 是 opt-in（PyMuPDF，AGPL，本地自用）
- NER 模型包：<https://modelscope.cn/models/Clukay416/legal-desens-cluener-onnx>
- 可逆性靠**位置映射**（不靠字符串替换）；还原前用 **SHA-256** 防错配

## 用途优先——先想清楚再动手

Skill 根据用途选择并显式传 profile；CLI 自身仍有默认值：

- **内部分析 / 给模型看 / 保留时间和金额** → `--profile labor`
- **对外发送 / 公开 / 接收方不可控** → `--profile strict`
- 用途不明 → 问一句"内部分析还是对外发送"，不要静默套默认

其他运行时规则（格式路由、审核触发、安全边界、三层验证报告）见 [`SKILL.md`](SKILL.md)。

## 快速安装

```bash
cd legal-mask
bash scripts/install_with_model.sh   # pip install . + NER 模型下载/校验/自检
```

可选 extras：`.[ocr]`（图片/扫描件）、`.[pdf]`（PDF 直接输入，AGPL）、`.[parse-docling]`（Docling，重）。

细节：[`references/install.md`](references/install.md)。

## 快速使用

```bash
# 先建交付目录与本地敏感工作目录；原件保持原位
mkdir -p deliver work
legal-desens ner-inspect
# 下例显式仅用正则；自检通过后去掉 --regex-only 可启用 NER
legal-desens redact 材料.docx --profile labor --regex-only \
  --out deliver/材料.redacted.docx --map work/材料.map.json --audit work/材料.audit.json

# 批处理：保留敏感工作文件，仅把 final_redacted_md 中的文件作为交付物
legal-desens batch-redact-case --input 材料目录 --out 批处理结果 \
  --profile labor --regex-only --cleanup archive

# 还原
legal-desens restore deliver/材料.redacted.docx --map work/材料.map.json --out work/材料.restored.docx

# 文本层 PDF 审核：生成敏感预览，审核后按 review.md 创建 decisions.json
legal-desens prepare 文本材料.pdf --profile labor --regex-only \
  --preview-md work/preview.md --manifest work/manifest.json --map work/source-map.json
# 仅适合需要局部星号遮盖的情况；此命令不受 profile 替换样式控制
legal-desens redact 文本材料.pdf --decisions work/decisions.json --source-map work/source-map.json \
  --out deliver/材料.redacted.pdf --map work/材料.map.json --audit work/材料.audit.json
```

扫描/混合 PDF 使用审核后的 boxes 与显式 `--document-kind`，不走 decisions。完整隐藏字段用自动 profile 脱敏、placeholder 文本导出或 PDF 区域遮盖。数据结构、示例与选择依据见 [references/review.md](references/review.md)，总入口是 [SKILL.md](SKILL.md)。

需要丢弃批处理工作文件时才使用 `--cleanup delete --confirm-delete`；删除会失去 map 及原格式脱敏中间产物，不能再承诺还原。

## 可直接发给 Agent 的安装提示词

```text
请安装并学会使用本地材料脱敏 skill：legal-mask。
源码：https://github.com/Clukay-Fun/lawchers-skills/tree/main/legal-mask

它是什么：通用中文脱敏 CLI/skill。可逆脱敏走位置映射（SHA-256 防错配），
图片/扫描件走不可逆 OCR 派生。profile 由**用途**决定：labor（内部分析，保留时间金额）
或 strict（对外发送，全脱）。人名/机构/地址走可选 NER，本机运行。命令：legal-desens。

先读文档：README.md → SKILL.md（决策与规则）；开发维护时再读 AGENTS.md / CLAUDE.md。
再安装（含 NER 模型）：
  git clone https://github.com/Clukay-Fun/lawchers-skills.git
  cd lawchers-skills/legal-mask
  bash scripts/install_with_model.sh
可选 extras 按需：pip install ".[ocr]"、".[pdf]"、".[parse-docling]"。
自测：python3 -m legal_desens.cli ner-inspect + python3 -m pytest -q。

规矩：ner-inspect 没过时按 SKILL 尝试修复，仍失败则显式传 --regex-only 并在报告注明；
不粘贴原文/map；不做 git 操作。
```

## 自测

```bash
pip install ".[dev]" && pytest              # 核心
pip install ".[dev,ocr,pdf]" && pytest      # 全量
```

未装模型时 NER 用例自动 skip，属正常。

## 环境要求

- Python ≥ 3.9
- 默认依赖（`pip install .`）：`onnxruntime`、`tokenizers`、`lxml`、`python-docx`、`openpyxl`
- 各 extra 与环境变量：[`references/install.md`](references/install.md)

## Profile 语义

| profile | 时间 | 金额 | 身份/联系方式/证件/账号/地址/机构 |
|---|---|---|---|
| `labor` | 保留 | 保留 | 脱敏 |
| `strict` | 脱敏 | 脱敏 | 脱敏 |

扩展新场景（刑事 / 商事 / 婚家 / 医疗等）不改核心引擎，只加 profile + allow/deny + 规则 + 验收样本；目前仅 `labor` / `strict` 已内置并验证。

## 安全约定

- map、source-map、preview、manifest、OCR 和审核文件含原文，勿入 git、聊天或对外交付目录。
- 报告只讲类型和计数，不粘原文。
- NER 是 best-effort，不是安全保证。
- 像素遮盖成功 ≠ 敏感内容全部识别（见 `SKILL.md` §6）。
- `[pdf]` extra 含 AGPL 依赖，仅本地自用。

## 目录结构

```text
legal-mask/
├── SKILL.md                     六节运行时规则
├── AGENTS.md                    开发/维护约束
├── CLAUDE.md                    Claude Code 开发约束
├── README.md                    安装与入口
├── references/
│   ├── install.md               安装、wheelhouse、env vars
│   ├── formats.md               各格式实现细节
│   ├── review.md                审核 JSON、坐标与导出衔接
│   ├── debug.md                 ner-inspect / paths / 诊断
│   ├── known-gaps.md            未验证路径与遗留格式
│   └── optional-ner-models.md   候选 NER 模型
├── legal_desens/                CLI 与引擎
├── rules/                       正则规则
├── scripts/                     安装脚本
└── tests/                       pytest
```

## 故障排查

见 [`references/debug.md`](references/debug.md)。反馈问题时附 `paths --json` 与 `ner-inspect` 输出，**不要**附 `map.json` 或原文。
