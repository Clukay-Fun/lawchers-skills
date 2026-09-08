# 已知能力缺口

主 `SKILL.md` 不承诺以下路径；未来落地要走"六问"再进 A/B/C。

## .pptx / .html

- `redact-scan` **不接受**这两类输入。
- `parse` 底层是 Docling，Docling 声称支持 pptx/html，但本项目**未针对这两类输入建立测试或验收**；不进主路由。
- 处理方式：先转成受支持格式（`.pptx` → `.pdf` 或 `.docx`；`.html` → `.md` 或 `.pdf`）再走对应管线。
- 若未来要正式支持，须补：Docling 输入格式清单验证、跨版式实体测试、失败行为定义、audit locator 语义、六问答复。

## 扫描 / hybrid PDF 的 `--decisions` 导出

- `redact --decisions --source-map` 当前仅支持：TXT/MD、DOCX、**text-layer PDF**；CSV/XLSX 不支持。
- scan-only PDF、混排（部分页有文本层、部分无）PDF 明确不支持 decisions 导出，CLI 会直接报错。
- 变通：审核页归一化矩形 boxes，运行 `mask-export --document-kind pdf-scan` 或 `pdf-hybrid`；也可用 `redact-scan` 自动像素脱敏。坐标转换见 [review.md](review.md)。

## 审核导出的样式与验证

- decisions 的 redact 动作采用局部星号遮盖，会保留部分原字符；不支持 replace 动作或任意替换文本。完整字段替换用自动 profile 路径、placeholder 文本导出或 PDF 框选。
- decisions 的 TXT/MD 输出未完整保留自动路径的 BOM 等还原元信息，不能承诺所有输入字节级往返；有 map 也不自动代表可还原。
- text-export 可能对错位片段重新查找、忽略无效/重叠项；mask-export 的扫描路径不执行独立像素复核。需要对照已选内容核验输出，不能仅凭成功状态或计数作完整验证承诺。
- preview、source-map、manifest 都包含原文，不是可对外发的脱敏文件。

## 遗留 Office / iWork / WPS

- `.doc / .xls / .wps / .et / .dps / .pages / .numbers / .key` **不支持**。
- 必须先转成 `.docx / .xlsx` 或 `.pdf / 图像` 等支持格式；PPTX 仍需进一步转换。

## OCR 语种

- RapidOCR 默认中英模型；**其他语种未验证**。
- 混排多语种、竖排、手写体、繁体简化程度高的扫描件识别率会显著下降；低置信度行进 audit warnings，但**不阻断产出**——依赖使用方读 warnings 决定是否人工兜底。

## NER 覆盖

- 通用 CLUENER 模型，非法律领域微调：
  - 公司名尾段（"XX 有限公司"末字段）易漏
  - 地址门牌号易漏
  - 无 MONEY 实体（走 regex）
- 即使 `ner-inspect` 通过，**不得**在最终报告里表述为"公司名/人名/地址全部识别"；只写 `regex+ner (best-effort)` 与命中计数。

## 第二检测引擎

- 目前只 regex + 一个 NER。第二 NER / LLM 判别 / 领域微调模型均属 D 类实验，未进承诺矩阵。

## 印章检测

- `detect-seals` 是 best-effort：几何 + 颜色启发，无监督模型；漏检/误检均可能。
- 输出仅供人工在 `mask-export` 前参考，不作为承诺覆盖印章的依据。

## 登记规则

新能力进主路由前，先在本仓库的对应 plan 里回答六问：
1. 可逆？byte / content？
2. `map.json` 存什么 locator？
3. audit 扫什么？
4. restore 支持？
5. 部分失败时 CLI 报错 / 警告 / 跳过 / 隔离？
6. agent 应调哪个命令？

没有回答完整的能力，写在本文件里当已知缺口，不进 SKILL 主路由。
