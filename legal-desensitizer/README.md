# legal-desensitizer

文档脱敏 CLI：对 `.txt / .md / .csv / .docx / .xlsx` 做**可逆脱敏、映射、还原、审计**。正则引擎开箱即用；人名/地址/机构名等实体识别可选接入本地 NER（ONNX）模型。图片/扫描件可走**不可逆** OCR 派生（可选 `[ocr]` extra）。

- 命令：`legal-desens`
- 可逆性靠**位置映射**（不靠字符串替换）；还原前用 **SHA-256** 防错配。
- **commercial-safe**：默认栈不含 AGPL/商用限制依赖（PyMuPDF 已移除），PDF 不在 core 支持。

---

## 给 AI 代理：按此顺序执行

```text
1. 安装          pip install .
2. 自测          pytest            # 全绿再继续
3. 判定 NER 可用  legal-desens ner-inspect   # 成功才用 NER，否则 --regex-only
4. 脱敏真实文档    legal-desens redact <file> ...
5. 汇报          模式(regex-only/regex+ner) + 实体数 + 审计/残留扫描结果
```

调用规范与安全边界见 `SKILL.md`、`AGENTS.md`、`CLAUDE.md`，使用前必读。

---

## 环境要求

- Python ≥ 3.9
- 依赖（`pip install .` 自动装）：`onnxruntime`、`tokenizers`、`lxml`、`python-docx`、`openpyxl`
- **NER 可选**：需要本地 RobertaCrfNerModel（ONNX）。若本机已安装华宇远点「智能文档脱敏系统」，模型就在 `/Applications/Desensitization/ydner_onnx/`，可一键导入（见下）。没有模型也能用，只是退化为 `--regex-only`。

## 安装

```bash
cd legal-desensitizer
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install .            # 或 pip install -e ".[dev]" 做开发
```

安装后 `legal-desens` 命令可用：

```bash
legal-desens --help
```

### 安装并准备 NER 模型（一条命令）

交付机器上若已安装华宇远点「智能文档脱敏系统」，推荐使用安装脚本把 CLI 和本地 NER 模型一起准备好：

```bash
cd legal-desensitizer
bash scripts/install_with_model.sh
```

脚本会执行：

```text
pip install .
legal-desens install-model --from-app
legal-desens ner-inspect
```

常用环境变量：

```bash
# App 模型目录不在默认路径时
LEGAL_DESENS_MODEL_SRC=/path/to/ydner_onnx bash scripts/install_with_model.sh

# 只安装 CLI，不安装模型
LEGAL_DESENS_SKIP_MODEL=1 bash scripts/install_with_model.sh

# 强制重装模型
LEGAL_DESENS_FORCE_MODEL=1 bash scripts/install_with_model.sh
```

### 离线 / 免编译安装（两种分发物）

不想每台机器联网装依赖时，有两种免编译分发物。每种产物均附 SHA-256 校验清单。

#### A) wheelhouse 离线安装（同平台、有 Python ≥ 3.9）

构建（需在目标平台上执行）：

```bash
bash scripts/build_wheelhouse.sh
# 产出 dist/wheelhouse-<platform>/，全为预编译 wheel
```

安装（断网、`--no-index` 强制离线）：

```bash
python3 -m venv /tmp/clean && source /tmp/clean/bin/activate
pip install --no-index --find-links=dist/wheelhouse-<platform> legal-desens
legal-desens --help
```

#### B) 单可执行文件（零依赖、不需 Python）

构建（需在目标平台上执行）：

```bash
bash scripts/build_binary.sh
# 产出 dist/legal-desens（单文件，含所有依赖）
```

使用：

```bash
./dist/legal-desens redact input.txt --regex-only --out out.txt --map m.json --audit a.json
./dist/legal-desens restore out.txt --map m.json --out restored.txt
```

#### 校验清单

```bash
# 查看 SHA-256
cat dist/wheelhouse-<platform>/SHA256SUMS.txt
cat dist/legal-desens-SHA256.txt
```

> 两种分发物都**不含 NER 模型**；启用 NER 仍走下文的 `install-model`。
> `--regex-only` 模式无需模型，两种产物均开箱可用。

## 自测（处理真实文档前必做）

```bash
pip install ".[dev]"          # 装 pytest（不含 OCR）
pytest                        # 覆盖 txt/md/csv/docx/xlsx、跨 run、sharedStrings、BOM/CRLF、错配等

# 若要连 OCR scan 测试一起跑，需装 ocr extra，否则那部分用例会因缺依赖失败：
pip install ".[dev,ocr]" && pytest
```

> 不装 `[ocr]` 时，core（txt/md/csv/docx/xlsx）测试全绿即可视为可用；OCR scan 相关用例需 `[ocr]` extra 才会通过。
> NER 相关用例在未装模型时自动跳过（skipped），属正常。

## 安装 NER 模型（可选，启用实体识别）

```bash
# 主模式：从本机已装 App 导入（无网络、无再分发风险）
legal-desens install-model --from-app
# 若 App 不在默认路径，用 --src 指定模型目录：
# legal-desens install-model --from-app --src /path/to/ydner_onnx

# 或下载模式（需你提供包 URL 与校验值）
# legal-desens install-model --url <URL> --sha256 <HASH>
```

模型落地到 `~/.legal-desens/models/roberta-crf-ner/`。验证：

```bash
legal-desens ner-inspect      # 打印模型 I/O 与 label；成功 = NER 可用
```

NER 模型搜索顺序：`--model-dir` → `LEGAL_DESENS_MODEL_DIR` → `~/.legal-desens/models/roberta-crf-ner` → `/Applications/Desensitization/ydner_onnx`（兜底）。

---

## 使用

### 各格式能力一览（决策表）

| 格式 | 支持动作 | 还原口径 | 还原前提 |
|------|----------|----------|----------|
| `.txt`  | redact / restore / audit | **字节级**一致 | redacted.txt + map.json（校验 redacted_sha256） |
| `.md`   | redact / restore / audit | **字节级**一致 | redacted.md + map.json |
| `.csv`  | redact / restore / audit | **字节级**一致（仅改 cell 文本，保留 dialect） | redacted.csv + map.json |
| `.docx` | redact / restore / audit | **内容级**（提取文本一致） | redacted.docx + map.json |
| `.xlsx` | redact / restore / audit | **内容级**（单元格文本一致） | redacted.xlsx + map.json |
| 图片 / 扫描件 | `redact-scan`（不可逆） | **不支持还原** | 需 `[ocr]` extra，输出脱敏 Markdown 派生副本 |
| `.pdf`  | 不支持 | — | PyMuPDF 已移除（AGPL）；扫描型 PDF 走 `redact-scan` |
| `.doc/.xls/.wps/...` | 不支持 | — | 先转换为 `.docx/.xlsx` 再处理 |

每次 redact 产出三件套：`<name>.redacted.<ext>`、`<name>.map.json`、`<name>.audit.json`。

### 脱敏（redact）

```bash
# 纯文本，仅正则
legal-desens redact input.txt \
  --level strict --regex-only \
  --out out.redacted.txt --map out.map.json --audit out.audit.json

# Word，启用 NER（需先 install-model 且 ner-inspect 通过）
legal-desens redact input.docx \
  --level strict \
  --out input.redacted.docx --map input.map.json --audit input.audit.json
```

> 不传 `--regex-only` 即尝试 `regex+ner`；模型缺失会**明确报错**，不会静默降级。

### 还原（restore）

```bash
legal-desens restore out.redacted.txt --map out.map.json --out out.restored.txt
```

- `.txt`：还原后自动比对 `source_sha256`，**字节一致才报成功**。
- `.docx/.xlsx`：内容级比对（需原文件在场才能校验）。
- 输入文件与 map 不匹配（`redacted_sha256` 不符）→ **报错退出，不强行还原**。

### 审计（audit）

```bash
legal-desens audit out.redacted.txt --map out.map.json --out out.audit.json
```

输出命中数量、实体类型分布、引擎来源、覆盖告警、残留扫描结果。

### 图片 / 扫描件 OCR（不可逆，可选）

```bash
pip install ".[ocr]"        # 装 RapidOCR（轻量，ONNXRuntime）
legal-desens redact-scan input.png --ocr rapidocr \
  --out input.redacted.md --map input.map.json --audit input.audit.json
```

- **不可逆**：OCR/解析丢失原位置，map 标 `restore_supported:false`、`best_effort:true`，**不支持 restore**。
- OCR 可能漏字/认错，残留扫描只覆盖识别出来的文本；低置信度行进 audit warning。
- 复杂文档解析可选 `parse`（需 `[parse-docling]` extra，较重，默认不装）。

---

## 真机脱敏流程（端到端）

```bash
# 1) 安装、准备 NER，并自测
bash scripts/install_with_model.sh
pip install ".[dev]" && pytest

# 2) 确认 NER 可用
legal-desens ner-inspect            # 成功 → 下一步去掉 --regex-only

# 3) 脱敏一份真实文档
legal-desens redact 合同.docx \
  --level strict \
  --out 合同.redacted.docx --map 合同.map.json --audit 合同.audit.json

# 4) 核对审计
cat 合同.audit.json                  # 看 summary 与 residual_scan / warnings

# 5)（需要时）还原
legal-desens restore 合同.redacted.docx --map 合同.map.json --out 合同.restored.docx
```

## 安全约定

- **`map.json` 是敏感文件**（含原文↔标签映射），妥善保管、勿入 git、勿粘到聊天里。
- 不要把原文敏感内容回贴到对话中。
- redacted 文件与 map 不匹配时**不要强行还原**。
- 模型未装时如实使用 `--regex-only` 并在报告中说明，不要假装跑了 NER。

## 故障排查

- `legal-desens: command not found` → 确认已 `pip install .` 且 venv 已激活。
- 编辑模式安装报错（旧 pip）→ 先 `pip install --upgrade pip`。
- `ner-inspect` 报找不到模型 → 先 `install-model --from-app`，或用 `--model-dir` 指定。
- 非 `--regex-only` 报模型错误 → 这是预期的"不静默降级"，装好模型或显式加 `--regex-only`。

## 规则

正则规则在 `rules/rules.json`（手机号、身份证、邮箱、案号、统一社会信用代码等）。可用 `--rules <path>` 指定自定义规则文件。
