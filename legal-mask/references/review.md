# 审核数据与导出

需要补漏、保留误识或区域遮盖时读本文。示例 `work/` 存敏感材料，`deliver/` 只存脱敏产物；先创建目录。示例用 `--regex-only`，NER 自检通过后可去掉。所有定位都基于同一份原文，不能混用不同提取方法的偏移。

## 自动路径的例外策略

`redact`、`redact-scan`、`batch-redact-case` 接受 `--allowlist` / `--denylist`（UTF-8，每行一个词）。allowlist 保留、denylist 强制纳入处理；复核重叠项的实际输出，不把词表当成完整检测保证。

`--entity-policy` 是 JSON，例如 `{"preserve_types":["MONEY"],"force_redact_types":["DATE"]}`，由 `redact`、`redact-scan`、`prepare`、批处理读取。prepare 没有 allow/deny 参数，需要词项例外时在 decisions 中按位置表达。

## 文本与 DOCX / 文本 PDF 的 decisions

```bash
legal-desens prepare input.docx --profile labor --regex-only \
  --preview-md work/preview.md --manifest work/manifest.json --map work/source-map.json
legal-desens redact input.docx --decisions work/decisions.json --source-map work/source-map.json \
  --out deliver/redacted.docx --map work/redacted.map.json --audit work/redacted.audit.json
```

prepare 不生成 decisions。由 agent 阅读 `manifest.candidates` 和 `source-map.blocks`，为候选添加 action；补漏项从原文 block 定位。数据是 JSON 数组，例如：

```json
[{"id":"manual_1","blockId":"原有 block 的 id","start":3,"end":14,"entityType":"PHONE","action":"redact"}]
```

- `start` / `end` 是 **block 内**从 0 开始的字符偏移，左闭右开，不能用全文偏移或 UTF-8 字节偏移。blockId 必须来自本次 source-map。
- action 仅 `redact` / `keep`；缺失或未知动作会报错。未列入的内容不处理；审查遗漏不能只看候选计数。
- DOCX 每条限制在一个段落 block 内；跨段落片段分别建立条目。`sourceLocator` 如提供，必须与 source-map 一致。
- 执行前 CLI 校验 `source_sha256`。不匹配或缺失时重新 prepare 并审核，不能直接改哈希绕过。
- 该路径使用类型相关的局部星号遮盖（例如手机号保留首尾）。`--profile strict` 不会改变它的替换样式，也不重新检测。完整隐藏字段应改用自动 strict 路径、下面的 placeholder 文本导出或 PDF boxes。
- TXT/MD、DOCX、文本 PDF 支持；CSV/XLSX/扫描 PDF/混合 PDF 不支持。自动 redact 的还原承诺不直接套用于 decisions 输出，详见 [known-gaps.md](known-gaps.md)。

检查 audit 的 `summary.redact_requested`、`redact_applied` 和 `residual_scan.passed`。位置验证只检查所选位置，不能证明候选之外没有遗漏。

## PDF boxes

```bash
legal-desens render-pages input.pdf --dpi 200 --out-dir work/pages --out work/pages.json
legal-desens analyze input.pdf --out work/ocr.json
legal-desens detect-seals input.pdf --out work/seals.json
legal-desens mask-export input.pdf --boxes work/boxes.json --document-kind pdf-scan \
  --out deliver/redacted.pdf --audit work/mask.audit.json
```

按需运行：页图用于目视审核，analyze 提供 OCR 框，detect-seals 仅在需要处理红章时辅助定位。导出时明确选择 `pdf-text`、`pdf-scan`、`pdf-hybrid`，不依赖默认值。

boxes 是审核后选中的区域数组，不能直接传整个 analyze/seals 输出对象：

```json
[{"id":"box_1","page":1,"x":0.1,"y":0.2,"width":0.3,"height":0.05,"source":"manual","entityType":"PHONE"}]
```

page 从 **1** 开始；坐标从页面左上角开始，x/width 除以页宽，y/height 除以页高，全部归一到 `[0,1]`。width/height 为正且不越界。CLI 接收轴对齐矩形，不接 polygon 点数组；OCR 像素 polygon 先取包围矩形，再按同 DPI 页图宽高归一。检查选区没有因旋转、缩放或裁切错位。

文本 PDF 删除框内文本再加黑框；扫描/混合 PDF 在像素上画黑框并重建图像化 PDF。当前 scan-mask audit 的 `passed` 不是独立像素复核，不能只凭它或 `boxes_applied` 宣称遮盖完整。逐页查看输出选区，并复核是否漏框。详见 [formats.md](formats.md)。

## 导出脱敏文本

`text-export` 接收 entities 数组，每项是 `{"original":"待处理片段","entity_type":"PHONE","start":3,"end":14}`。不同于 decisions，它需要原文片段和**导出全文**的绝对偏移。

从 prepare 转换时，以 source-map 的 block 文本取 original，再计算其在导出文本中的位置。所有 PDF 都需要 `--ocr-text`：把按顺序拼接的 OCR/block 文本保存到 `work/ocr.txt`，按这份文本计算绝对偏移并一起传入；不要把 block 内偏移直接当全文偏移。DOCX 默认只提取正文段落，不包含表格、页眉页脚等；需要这些内容时也可提供完整的预提取文本与匹配的 entities。

```bash
legal-desens text-export input.pdf --entities work/entities.json --ocr-text work/ocr.txt \
  --mode placeholder --format md --out deliver/redacted.md
```

placeholder 完整替换选中的片段；star 留部分字符。此命令没有 profile 参数、不产生可逆 map，也不产生与 redact 相同的 audit。遇到偏移不匹配时现有实现可能重新搜索原文，遇到无效或重叠项可能跳过；先核对片段、位置和重叠，再逐项核对最终文本。不可把输出计数视为独立验证。
