# 安装与模型准备

主 `SKILL.md` 不含安装细节；需要装或换机时读本文。

## 一条命令：CLI + NER 模型

```bash
cd legal-mask
bash scripts/install_with_model.sh
```

脚本会依次执行：`pip install .` → 从 ModelScope 下载 NER ONNX 模型包 → 校验 SHA-256 → `legal-desens install-model` → `legal-desens ner-inspect`（含 self-test）。

**这是安装便利，不是能力保证**。装好后 NER 仍是 best-effort 增强，不表示识别覆盖完整（见主 `SKILL.md` 安全边界）。

## 可选 extras

```bash
pip install ".[ocr]"    # RapidOCR，图片/扫描件
pip install ".[pdf]"    # PyMuPDF（AGPL，仅本地自用），PDF 直接输入
pip install ".[parse-docling]"  # Docling + PyTorch，重
pip install ".[dev]"    # pytest + Pillow
```

默认 core 不含 AGPL 依赖（`pip install .`），保持 commercial-safe。

## 常用环境变量

下面是可用变量，按需通过 `export` 或命令前缀传给脚本，不要把占位值全部复制执行。例如：`LEGAL_DESENS_SKIP_MODEL=1 bash scripts/install_with_model.sh`。

```bash
# 覆盖 ModelScope 地址
LEGAL_DESENS_MODEL_URL="…"
LEGAL_DESENS_MODEL_SHA256="…"

# 已有本地兼容模型目录时导入
LEGAL_DESENS_MODEL_SRC=/path/to/model_dir

# 仅装 CLI，跳过模型（走 --regex-only）
LEGAL_DESENS_SKIP_MODEL=1

# 强制重装模型
LEGAL_DESENS_FORCE_MODEL=1

# 本地 wheelhouse 加速/离线
LEGAL_DESENS_WHEELHOUSE=dist/wheelhouse-<platform>
```

## 离线 / 免编译

- `bash scripts/build_wheelhouse.sh` → `dist/wheelhouse-<platform>/`，`pip install --no-index --find-links=…` 安装
- `bash scripts/build_binary.sh` → `dist/legal-desens` 单可执行文件（零 Python 依赖）
- 两种产物**均不含 NER 模型**；`--regex-only` 开箱可用，启用 NER 仍需 `install-model`

## NER 模型搜索顺序

`--model-dir` → `LEGAL_DESENS_MODEL_DIR` → `~/.legal-desens/models/roberta-crf-ner` → `/Applications/Desensitization/ydner_onnx`（兜底）。

当前公开模型包：<https://modelscope.cn/models/Clukay416/legal-desens-cluener-onnx>。候选模型 license/训练数据/局限见 [`optional-ner-models.md`](optional-ner-models.md)。

## 自测

```bash
pip install ".[dev]" && pytest             # 核心（txt/md/csv/docx/xlsx）
pip install ".[dev,ocr]" && pytest         # 加 OCR 用例
pip install ".[dev,ocr,pdf]" && pytest     # 全量
```

未装模型时，NER 用例自动 skip，属正常。

## 常见故障

- `legal-desens: command not found` → 用 `python3 -m legal_desens.cli …`
- `ner-inspect` 报 `self_test.passed=false` → 跑一次 `bash scripts/install_with_model.sh`；失败即 `--regex-only` + 报告说明
- 非 `--regex-only` 报模型错误 → 预期行为（不静默降级）
