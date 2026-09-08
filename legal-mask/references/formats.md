# 各格式内部实现

主 `SKILL.md` 只列路由；实现细节按需读本文。

## A1 字节级可逆（byte）

### .txt / .md
- redact/restore 字节级一致；保留 UTF-8 BOM、CRLF、行尾换行。
- .md 视为纯文本 + Markdown 格式；无 Markdown 语义解析。

### .csv
- 保留 dialect（分隔符、引号）、编码（BOM）、行尾、字段引用。
- 仅改单元格文本；结构不动。
- map locator：`type: csv, row, column`。

## A2 内容级可逆（content）

### .docx
- 覆盖 body、tables / text boxes、header、footer、footnotes、endnotes、comments。
- 同段落跨 run 实体支持；**跨段落实体不支持**（写入 audit warnings）。
- restore 保证提取文本一致，不保证 DOCX 字节一致。

### .xlsx
- 单元格文本（inline string / shared string）内容级。
- **公式单元格跳过**（audit warning）。
- shared strings 不在原位改；命中的单元格切换为 inline string。

## B 不可逆同格式派生

### 文本层 .pdf
- `redact input.pdf --out output.redacted.pdf`：原位真删除检测到的文字，扫描可提取容器中的残留原文。
- 需 `[pdf]` extra（PyMuPDF，AGPL）。
- 不可 restore；map 标 `restore_supported: false`, `best_effort: true`。
- 缺 `[pdf]` extra → 明确报错，不静默跳过。

### 图片（.png/.jpg/.jpeg/.tiff/.bmp）
- `redact-scan`：OCR → 白框像素遮盖 → 保持原图格式；同时保留脱敏 Markdown 中间文件。
- 需 `[ocr]` extra（RapidOCR）。
- map 标 `verification: redacted-pixels, restore_supported: false, best_effort: true, intermediate_markdown_file: …`。
- OCR 低置信度行（< 0.7）进 audit warnings；残留扫描只覆盖识别出来的文本。

### 扫描 .pdf
- `redact-scan input.pdf`：逐页渲染为 200 DPI PNG → OCR → 白框 → 图像化 PDF + per-page Markdown。
- 需 `[pdf]` + `[ocr]` extras。
- **输出是图像化 PDF**：不保留源 PDF 文本层、结构树、书签、表单语义、附件。
- OCR/NER 实例在页面间复用；中间图/OCR 文件写入系统临时目录，完成后删除，不在源目录留 `__pdf_pages/` 等。
- 像素复核失败：返回非零、仍写 map/audit/Markdown、把不完整产物改名 `*.INCOMPLETE_DO_NOT_USE.pdf` 而非占用请求的输出名。
- audit 的 `verification.failures` 只记页码 + 实体 ID/类型 + 遮盖类别，不记原文；审核 preview/source-map 等其他工作文件仍可能包含原文。

## C 派生审阅材料

- `parse`：Docling → Markdown（**不脱敏**）；需 `[parse-docling]` extra。
- 批处理产物：`SENSITIVE_REDACTION_REPORT_DO_NOT_UPLOAD.md`、`run_manifest.json`、`final_redacted_md/`。

## 验证字段与适用路径

| verification | 含义 |
|---|---|
| `byte` | 还原文件 SHA-256 == 原文件 SHA-256 |
| `content` | `extract_text(source) == extract_text(restored)`（非字节级） |
| `redacted-content` | 文本 PDF 自动脱敏的残留内容检查；仍取决于检测覆盖 |
| `redacted-pixels` | 图像/扫描 PDF 的像素处理及复核；看 audit 的 verification 对象，不能仅看 map 字符串 |
| `irreversible` | 旧版 Markdown 派生路径的不可逆标记，不是像素验证 |
| `applied_position_verification` | decisions 文本/DOCX 的 residual_scan.method，只验证已选位置 |
| `rect_based_extraction` | decisions 文本 PDF 的 residual_scan.method，结合 original_removed、replacement_written、position_verification |
| `pixel-black-block` | mask-export 的扫描/混合 PDF 路径；当前 passed 表示导出完成，未独立复核每个框的像素 |
| `redacted-content + pixel-black-block` | mask-export 的文本 PDF 路径，删除原文并检查框内可提取文本 |

`byte`/`content` 是还原口径；是否实际做了还原校验应另行说明。各路径输出结构不同，以实际 audit/map 为准；不要给所有产物套三件套要求。mask-export 只有 PDF 和可选 audit；text-export 不产出可逆 map 或同等 audit。

## 审核导出的范围

decisions 支持 TXT/MD/DOCX/文本 PDF，不支持 CSV/XLSX/扫描或混合 PDF。替换样式为局部星号，profile 不改变它。TXT/MD 自动路径保留 BOM 等特性的承诺不能直接套用于 decisions；需要还原时优先自动路径。具体 schema 和替代路线见 [review.md](review.md)。

## 输出三件套

每次 `redact` 产出：

```text
<name>.redacted.<ext>   脱敏产物
<name>.map.json         位置映射（敏感文件）
<name>.audit.json       残留扫描 + 实体计数
```

Skill 要求显式传 `--out --map --audit`，这是调用约定；CLI 并非在所有路径都强制缺一报错。输出及审核原文分开存放。

## batch-redact-case 默认输出

```text
final_redacted_md/
SENSITIVE_REDACTION_REPORT_DO_NOT_UPLOAD.md
run_manifest.json
```

中间敏感产物落在 `_work_sensitive_do_not_upload/`；默认 `--cleanup delete` 需 `--confirm-delete`；调试用 `--cleanup none`；要留 map/audit 用 `--cleanup archive`。
