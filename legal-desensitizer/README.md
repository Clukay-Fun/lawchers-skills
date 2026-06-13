# legal-desensitizer

**通用案件材料脱敏 skill**：通用脱敏核心 + 场景化 profile。对 `.txt / .md / .csv / .docx / .xlsx` 做**可逆脱敏、映射、还原、审计**；图片/扫描件走**不可逆** OCR 派生（可选 `[ocr]` extra）。正则引擎开箱即用，人名/地址/机构名等实体识别可选接入本地 NER（ONNX）模型。

> 定位：通用案件材料脱敏工具，**已通过劳动案件场景首轮实战验收**。当前成熟 profile：`labor`（默认）。换刑事/商事/婚姻家事/医疗等场景时**不改核心引擎**，只新增/调整 profile + allowlist/denylist + 规则 + 验收样本。

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

## 安装 Skill 时同时准备模型

把本目录作为 Codex/Claude skill 安装后，还需要在同一目录执行一次安装脚本，脚本会同时完成：

```text
pip install .
下载 GitHub Release Asset 里的 NER ONNX 模型
校验 SHA-256
legal-desens ner-inspect
```

推荐命令：

```bash
cd legal-desensitizer
LEGAL_DESENS_MODEL_URL="https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
LEGAL_DESENS_MODEL_SHA256="d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703" \
bash scripts/install_with_model.sh
```

只复制 `SKILL.md` 或只执行 `pip install .` 不会自动下载 360MB 模型；这种情况下仍可用 `--regex-only`，但不能启用 NER。

---

## 环境要求

- Python ≥ 3.9
- 依赖（`pip install .` 自动装）：`onnxruntime`、`tokenizers`、`lxml`、`python-docx`、`openpyxl`
- **NER 可选（best-effort）**：默认 `--regex-only` 无需任何模型即可用。想额外识别人名/机构/地址，可接入一个**兼容的中文 token-classification ONNX 模型**：用自带脚本导出一个开源模型（推荐，见「启用 NER」一节），或自带模型用 `--model-dir` 指向。没有模型完全不影响使用。

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

> 默认 `--regex-only` 无需模型即可使用。若要启用 NER，推荐从本仓库 GitHub Release Asset 下载已经导出的 ONNX 模型包，并用 SHA-256 校验安装。

一条命令安装 CLI + 下载/安装 NER 模型：

```bash
cd legal-desensitizer
LEGAL_DESENS_MODEL_URL="https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
LEGAL_DESENS_MODEL_SHA256="d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703" \
bash scripts/install_with_model.sh
```

脚本会执行：

```text
pip install .
legal-desens install-model --url <GitHub Release Asset URL> --sha256 <SHA256>
legal-desens ner-inspect
```

常用环境变量：

```bash
# 从 GitHub Release Asset 下载模型（推荐）
LEGAL_DESENS_MODEL_URL="https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
LEGAL_DESENS_MODEL_SHA256="d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703" \
bash scripts/install_with_model.sh

# legacy/import-only：已有本地兼容模型目录时导入
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

## 启用 NER（可选，best-effort）

默认 `--regex-only` 不需要模型。要额外识别人名/机构/地址，按下面任一方式接入一个兼容的 ONNX 模型。

### 推荐：从 GitHub Release Asset 下载模型包

模型权重不进入 git 仓库。推荐把导出的 ONNX 模型包放到本仓库的 GitHub Release Asset 中，然后用 URL + SHA-256 安装：

```bash
legal-desens install-model \
  --url "https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
  --sha256 "d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703"

legal-desens ner-inspect
```

Release Asset 模型包必须是 `.zip` 或 `.tar.gz`，解压后顶层包含：

```text
model.onnx
config.json
vocab.txt
labels.json 或 config.json 内含 id2label/label2id
```

建议 Release 命名：

```text
tag:   legal-desens-ner-v0.1
asset: bert4ner-base-chinese-onnx.zip
```

下载链接和 SHA-256 应同步记录在 [`references/optional-ner-models.md`](references/optional-ner-models.md)。

### 本地导出开源模型

用自带脚本把 HuggingFace 上的中文 NER 模型导出成可用目录（示例为 Apache-2.0 候选）：

```bash
pip install ".[dev]" transformers torch onnx     # 仅导出时需要
python scripts/export_hf_ner_onnx.py \
  --hf-model shibing624/bert4ner-base-chinese \
  --output-dir ~/ner-bert4ner
legal-desens ner-inspect --model-dir ~/ner-bert4ner          # 成功 = NER 可用
legal-desens redact input.txt --model-dir ~/ner-bert4ner --out ... --map ... --audit ...
```

候选模型的 license、训练数据与已知局限见 [`references/optional-ner-models.md`](references/optional-ner-models.md)。

### 其他方式

```bash
# 自托管模型包下载（GitHub Release Asset / 对象存储均可）
legal-desens install-model --url <URL> --sha256 <HASH>

# legacy：若本机恰好已有一个兼容模型目录，可直接导入
legal-desens install-model --from-app --src /path/to/model_dir
```

`install-model` 装好的模型落地到 `~/.legal-desens/models/roberta-crf-ner/`。

NER 模型搜索顺序：`--model-dir` → `LEGAL_DESENS_MODEL_DIR` → `~/.legal-desens/models/roberta-crf-ner` → `/Applications/Desensitization/ydner_onnx`（兜底）。

> **NER 是可选 best-effort 增强，不是安全保证。** 默认 `--regex-only` 处理结构化 PII（手机/身份证/邮箱/案号/信用代码/金额）为可靠核心。启用 NER 可额外识别人名/地址/机构名，但通用模型可能漏公司名、漏地址尾段、无金额识别。audit 中会标注 `best_effort`。参考 `references/optional-ner-models.md` 了解候选模型详情。

---

## 脱敏策略（场景 profile）

**通用核心 + 场景 profile**：引擎通用，"哪些类型脱、哪些保留、用什么标签"由 profile 配置决定。用 `--profile <name>` 选择（默认 `labor`）。

| profile | 适用 | 时间 | 金额 | 身份/联系方式/证件/银行账号/地址/机构 |
|---|---|---|---|---|
| `labor`（默认，已验证） | 劳动争议/民事，需保留时间线与金额计算 | 保留 | 保留 | 脱敏 |
| `strict`（全脱/安全优先） | 不需保留任何可识别信息 | 脱敏 | 脱敏 | 脱敏 |

标签为无编号中文方括号：`【姓名】【机构】【地址】【手机号】…`，可逆性不受影响（restore 按位置回填，不靠标签文本）。

```bash
legal-desens redact input.docx              # 默认 labor：保留时间/金额
legal-desens redact input.docx --profile strict   # 全脱
```

**扩展到新场景**（不改核心引擎，只加配置 + 验收样本）：

| 场景 | 取向（示例方向，尚未内置 profile） |
|---|---|
| 劳动（已验证） | 保留时间线、金额 |
| 刑事 | 可保留案发时间；更严处理地点、人员关系、未成年人信息 |
| 商事 | 可保留金额；重合同编号、账户、客户名、商业秘密词 |
| 婚姻家事 | 重姓名、住址、子女信息、证件、联系方式 |
| 医疗 | 重姓名、证件、病历号；医院/医生是否脱按用途定 |

> 目前仅 `labor` / `strict` 已内置并验证；其余为扩展方向（按需新增 profile + allow/deny + 规则 + 验收样本）。

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
# 纯文本，仅正则（默认 labor profile：保留时间/金额）
legal-desens redact input.txt \
  --regex-only \
  --out out.redacted.txt --map out.map.json --audit out.audit.json

# Word，启用 NER（需先 install-model 且 ner-inspect 通过）
legal-desens redact input.docx \
  --out input.redacted.docx --map input.map.json --audit input.audit.json

# 全脱敏（含时间/金额）：切 strict profile
legal-desens redact input.docx --profile strict \
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
# 1) 安装并自测（默认 regex-only，无需任何模型）
pip install . && pip install ".[dev]" && pytest

# 2) 脱敏一份真实文档（默认 labor profile，regex-only 即可用）
legal-desens redact 合同.docx \
  --regex-only \
  --out 合同.redacted.docx --map 合同.map.json --audit 合同.audit.json

# 3) 核对审计
cat 合同.audit.json                  # 看 summary 与 residual_scan / warnings

# 4)（需要时）还原
legal-desens restore 合同.redacted.docx --map 合同.map.json --out 合同.restored.docx

# 5)（可选）启用 NER：导出一个开源模型后，去掉 --regex-only
#    见上文「启用 NER」一节；NER 为 best-effort，可能漏公司名/地址
```

## 安全约定

- **`map.json` 是敏感文件**（含原文↔标签映射），妥善保管、勿入 git、勿粘到聊天里。
- 不要把原文敏感内容回贴到对话中。
- redacted 文件与 map 不匹配时**不要强行还原**。
- 模型未装时如实使用 `--regex-only` 并在报告中说明，不要假装跑了 NER。
- **NER 是 best-effort，不是安全保证。** 启用 NER 时报告"regex+ner (best-effort)"，注明可能漏公司名/地址，不得宣称 NER 覆盖完整。

## 故障排查

- `legal-desens: command not found` → 确认已 `pip install .` 且 venv 已激活。
- 编辑模式安装报错（旧 pip）→ 先 `pip install --upgrade pip`。
- `ner-inspect` 报找不到模型 → 先 `install-model --from-app`，或用 `--model-dir` 指定。
- 非 `--regex-only` 报模型错误 → 这是预期的"不静默降级"，装好模型或显式加 `--regex-only`。

## 规则

正则规则在 `rules/rules.json`（手机号、身份证、邮箱、案号、统一社会信用代码等）。可用 `--rules <path>` 指定自定义规则文件。
