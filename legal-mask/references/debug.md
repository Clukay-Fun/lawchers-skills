# 调试与诊断

出错时按此文排查；主 `SKILL.md` 不写深度步骤。

## `ner-inspect` 结果解读

```bash
legal-desens ner-inspect [--model-dir <path>]
```

- `model_dir` — 实际模型目录
- `model_io` — 输入/输出名称、形状、类型
- `id2label` / `tag_scheme` / `num_labels` — 标签映射与标注方式
- `self_test.passed: true` — 内置样例推理通过

仅在命令成功且 `self_test.passed=true` 时启用 NER。缺模型或自检失败，按 [install.md](install.md) 尝试一次修复，仍失败则由 agent 显式传 `--regex-only` 并说明。

`prepare` 可能把 NER 异常写入 manifest warnings 后继续；读取 `ner_unavailable`、`self_test.error` 等实际结果，不仅依赖退出码或请求的 mode。

## `paths` 命令

```bash
legal-desens paths --json
```

当前只输出 `{"rules":"实际规则文件路径"}`。模型位置看 `ner-inspect.model_dir`；模型搜索顺序见 [install.md](install.md)，不要期待 paths 返回 profile 或模型列表。

## 像素复核失败：`INCOMPLETE_DO_NOT_USE`

`redact-scan` 像素复核不过：
- 命令返回码非零
- 仍写 map / audit / Markdown
- 不完整 PDF 改名 `*.INCOMPLETE_DO_NOT_USE.pdf`，不占请求的输出名
- audit 的 `verification.failures`：`page / entity_id / entity_type / category`（不含原文）

处理：按 `verification.failures` 定位原始页，读 [review.md](review.md) 后审核 boxes，并用 `mask-export --document-kind pdf-scan`（混合 PDF 用 `pdf-hybrid`）导出和复核。扫描件不能使用 decisions 导出。图片可修正检测策略后重跑，或转 PDF 后做区域遮盖。

## Pipeline diagnostics 字段

`audit.json` 里 scan 流水线的关键字段：
- `pipeline_diagnostics`：流水线统计与各页诊断，字段随路径读取
- `warnings`：OCR 低置信度、识别限制等警告
- `verification.type / passed / failed_pages / failures / retry_attempted`：像素复核结果

map 的 `verification` 是字符串，audit 的同名字段可能是对象，不要混用。仅 Markdown 的旧路径会使用 `irreversible`，不能当作像素复核通过。

低置信度行不阻断产出但要在最终报告的"漏检风险"段落里点名。

## NER 调试

```bash
legal-desens ner-spans <input.txt> [--model-dir <path>] [--out spans.json]
```

导出 NER 抽出的 spans（type / start / end / score），用于比对模型是否漏识某类实体。**不要**用它作最终产物依据——它只对纯文本工作，不代表 docx/pdf 上的实际行为。

## 常见错误模式

| 症状 | 定位 | 处理 |
|---|---|---|
| `command not found: legal-desens` | 用户级 bin 目录不在 PATH | 改用 `python3 -m legal_desens.cli …` |
| `redact` 报 `NER model not available` | 未装/装错模型且没传 `--regex-only` | 装好模型或加 `--regex-only` |
| `redact-scan` 报 `PyMuPDF not installed` | 缺 `[pdf]` extra | `pip install ".[pdf]"` |
| `restore` 报 `sha256 mismatch` | 输入 redacted 文件与 map 不是同一次产出 | 先找匹配文件；有原件时可重跑，不覆盖仅存的还原材料 |
| decisions 报 `source_sha256 mismatch` | 审核后源文件变化或 source-map 缺失哈希 | 重新 prepare 并审核，不能只改哈希 |
| decisions 报 action 错误 | 缺少 action 或用了 replace 等未知动作 | 修正为 redact / keep 后重新审核 |
| DOCX 跨段落实体漏识 | 已知限制 | 每段片段分别建立 decision，不能跨 block |
| 输出目录出现 `__pdf_pages/` | 外部工具残留 | 报 bug；不应在源目录 |

## 环境变量诊断

```bash
LEGAL_DESENS_MODEL_DIR       # 显式指定模型目录
LEGAL_DESENS_MODEL_URL       # 覆盖下载地址
LEGAL_DESENS_MODEL_SHA256    # 覆盖校验哈希
LEGAL_DESENS_MODEL_SRC       # 从本地目录导入
LEGAL_DESENS_SKIP_MODEL=1    # 跳过模型安装
LEGAL_DESENS_FORCE_MODEL=1   # 强制重装
LEGAL_DESENS_WHEELHOUSE      # 离线 wheel 源
```

问题反馈请一并附 `paths --json` 与 `ner-inspect` 的完整输出；**不要**附 map.json 或原文。
