---
name: legal-mask
description: 使用本地 legal-desens CLI 为中文案件材料脱敏、还原脱敏文件或审核漏识与误识别。用户要求隐藏敏感信息、准备脱敏版材料或检查脱敏结果时使用。
---

# 材料脱敏

## 1. 适用范围与准备

根据用户的脱敏要求选择处理方式。仅要求分析案件或阅读材料，不自动附加脱敏任务。`legal-desens` 是处理核心；不在 PATH 时可用 `python3 -m legal_desens.cli`，安装或换机时读 [install.md](references/install.md)。

自动识别前运行 `legal-desens ner-inspect`。命令成功且 `self_test.passed=true` 才启用 NER；模型缺失或自检失败时，按安装指引尝试一次修复，仍失败则在 `redact`、`redact-scan`、`prepare` 或批处理命令中**显式传 `--regex-only`**并报告。用户明确仅用正则时直接传该参数，无需安装模型。CLI 不替 agent 保证降级；也要查看运行结果中的 `ner_unavailable` 等警告。详见 [debug.md](references/debug.md)。

## 2. 用途与处理策略

先理解用途、需保留的信息、是否需要还原以及最终输出格式，沿用已有要求，不重复询问。

| profile | 自动检测后的处理策略 | 典型用途 |
|---|---|---|
| `labor` | 隐去识别到的人名、机构、地址、电话、证件、账号、案号、密钥；保留日期、时间、金额 | 内部案件事实分析 |
| `strict` | 在 labor 基础上也隐去日期、时间、金额 | 对外发送、公开 |

用途明确时直接选，并显式传 `--profile`。用途与保留要求都不明时，询问内部分析还是对外发送；用户已给出完整脱留规则时按规则执行。需要例外时，自动脱敏可用 `--entity-policy`、`--allowlist`、`--denylist`；格式和适用命令见 [review.md](references/review.md)。

Profile 决定检测后哪些类型需处理，不保证识别完整，也不控制所有导出命令。`--decisions` 和 `text-export --mode star` 会保留部分原字符；完整隐藏已选字段时优先自动 profile 脱敏、`text-export --mode placeholder` 或 PDF 区域遮盖。不要把局部星号遮盖称为 strict 全字段替换。

需要还原时选择可逆路径，保存对应脱敏原格式文件与 map。仅有 Markdown 派生文本不能还原原 PDF 或 Office 文件。

## 3. 格式与命令路由

| 输入或目的 | 路径 | 能力边界 |
|---|---|---|
| TXT / MD / CSV | `redact` | 自动路径字节级可逆 |
| DOCX / XLSX | `redact` | 自动路径内容级可逆；XLSX 公式跳过 |
| 文本层 PDF | `redact`，需 `[pdf]` | 删除命中文本，不可还原 |
| 扫描/混合 PDF、图片 | `redact-scan`，需 `[ocr]`；PDF 另需 `[pdf]` | 白框像素遮盖；PDF 输出图像化，不可还原 |
| 审核后精确处理 TXT / MD / DOCX / 文本 PDF | `prepare` → decisions → `redact --decisions` | 局部星号替换；单独核对输出和还原边界 |
| 审核 PDF 区域、印章 | `render-pages` / `analyze` → boxes → `mask-export` | 页归一化矩形；文本 PDF 真删除后加黑框，扫描/混合 PDF 重建图像化副本 |
| 仅需脱敏文本 | `text-export --entities … --mode placeholder --format txt\|md\|docx` | 输入 PDF/DOCX/TXT/MD；PDF 均需预提取文本并传 `--ocr-text`，不保留原版式 |
| 目录批处理 | `batch-redact-case` | 默认交付 Markdown；留工作文件用 `--cleanup archive` |
| PPTX / HTML / 旧 Office、WPS、iWork | 先转换为支持格式 | 不承诺原生处理，见 [known-gaps.md](references/known-gaps.md) |
| 还原 | `restore <redacted> --map <map> --out <restored>` | TXT/MD/CSV/DOCX/XLSX；必须匹配同次产出的文件 |
| 独立残留审计 | `audit <redacted> --map <map> --out <audit>` | TXT/MD/CSV/DOCX/XLSX；PDF/图片读对应管线 audit |

自动 `redact` 必传 `--out --map --audit`；`redact-scan` 另传 `--md-out` 指定脱敏 Markdown。使用独立的交付目录与本地敏感工作目录，提前创建父目录。各格式覆盖范围、验证字段见 [formats.md](references/formats.md)。

## 4. 审核与补漏

普通任务直接自动脱敏。用户要求审核或返工、对外提供敏感合同/证据、扫描件或复杂版式、出现低置信度或残留疑点时，按格式复核。由 agent 按明确的脱留要求审查；确实影响结果且无法判断的项目再请用户决定。

执行审核导出前读 [review.md](references/review.md)，其中定义 JSON 数据结构和坐标转换：

- TXT/MD/DOCX/文本 PDF：`prepare` 生成原文预览、manifest 和 source-map；生成只含 `redact` / `keep` 的 decisions 后定点导出。补漏用新增 `redact` 条目；没有 `replace` 动作。原文改变后重新 prepare 并审核。
- 扫描/混合 PDF：检查页图与 OCR，生成审核后的 boxes；`mask-export` 显式传 `--document-kind pdf-scan` 或 `pdf-hybrid`。不走 decisions 导出。印章可用 `detect-seals` 辅助定位，仍需查看页图。
- 图片：查看原图与 `redact-scan` 结果；需手工框选时可转 PDF 后走区域审核，告知交付格式变化。
- CSV/XLSX：使用自动脱敏的 allow/deny 或类型策略修正后重跑；没有原格式 decisions 导出。不将 XLSX 输入 prepare。
- DOCX 跨段落：把需隐藏的每段片段分别标记，不生成跨 block 的 decision。

审核候选只涵盖已识别内容，还需查看原文/页图寻找遗漏。审核决定与实际产物逐项对应；`text-export` 或 boxes 文件不是可直接互换的 decisions 文件。

## 5. 敏感文件与失败处理

- map、source-map、preview、manifest、decisions、entities、OCR 文本及原始页图都可能含原文，保存在本地敏感工作目录，不贴入聊天或混入对外交付。批处理的 `SENSITIVE_REDACTION_REPORT_DO_NOT_UPLOAD.md` 同样敏感。
- 启用 NER 只表示 best-effort 增强；正则或 OCR 也会漏识。报告不承诺所有人名、机构、地址已找全。
- map 与脱敏文件 SHA 不匹配时不绕过还原校验，先寻找匹配文件；需要时用原件重跑。
- 批处理默认 `--cleanup delete` 需要 `--confirm-delete`，会删除工作文件和 map。要求还原或没有明确删除要求时用 `--cleanup archive`；仅在用户同意丢弃敏感工作文件后使用删除模式。
- 非零退出、验证失败或 `INCOMPLETE_DO_NOT_USE` 产物不能作为成功交付；查 [debug.md](references/debug.md) 后修复并复核。成功后按约定清理临时物料，保留还原所需文件。
- PDF 使用 opt-in `[pdf]` extra；本项目约定仅本地使用。默认安装不含该依赖。

## 6. 交付与验证结论

报告按任务规模简要覆盖以下内容，无须固定三段或重复与本次无关的风险：

1. 采用的 profile、例外规则、实际识别引擎，以及识别类型和数量；仅按审核列表导出时说明它没有重新自动检测。
2. 实际执行与验证结果：已选多少、处理多少、哪些检查通过。原样解释该路径的 audit 字段；字节/内容级还原校验不等于完整敏感信息检测。无独立像素复核时明确说明，不仅凭命令成功或计数就称“100% 遮盖验证通过”。
3. 本次残留疑点、OCR/NER 限制或未覆盖区域；未验证的部分如实标记。

交付脱敏产物和不含原文的简要报告，给出文件位置。需要还原时另给本地脱敏原格式文件与 map 的存放位置，并说明 map 敏感；PDF、图片、文本派生以及未经验证的审核导出不能承诺原文件还原。
