---
name: legal-desensitizer
description: "General-purpose Chinese case-material redaction skill using the local legal-desens CLI. Use when a user asks to desensitize case documents, run batch redaction, generate final Markdown and sensitive reports, restore/audit maps, install the GitHub Release NER model, or troubleshoot regex/NER/OCR redaction across txt, md, csv, docx, xlsx, and scanned images."
---

# Legal Desensitizer

Use the local `legal-desens` CLI for legal document redaction, restoration, and audit. The CLI is the sole capability core—this skill instructs agents how to call it correctly.

If `legal-desens` is not on `PATH` after installation, use the equivalent module form:

```bash
python3 -m legal_desens.cli <subcommand> ...
```

## Mandatory Bootstrap On Fresh Machines

When this skill is present but `legal-desens` or NER is not ready, do not stop at `ner-inspect` failure. First run the bootstrap from the project root:

```bash
bash scripts/install_with_model.sh
```

The script has the approved GitHub Release Asset URL and SHA-256 built in. It installs the CLI, downloads the NER ONNX model, verifies SHA-256, installs the model, and runs `legal-desens ner-inspect` including self-test. Use `LEGAL_DESENS_SKIP_MODEL=1` only when the user explicitly wants regex-only.

For faster/offline installs, first build or provide a wheelhouse and set `LEGAL_DESENS_WHEELHOUSE=/path/to/wheelhouse`. Do not use a stale wheelhouse.

## Quick Decision Table

Before running any command, determine the file extension:

| Format | `redact` | `restore` | `audit` | verification | restore prerequisite |
|--------|----------|-----------|---------|--------------|----------------------|
| `.txt` | yes | yes | yes | byte | `redacted.txt` + `map.json`, `redacted_sha256` must match |
| `.md` | yes | yes | yes | byte | `redacted.md` + `map.json`, `redacted_sha256` must match |
| `.csv` | yes | yes | yes | byte | `redacted.csv` + `map.json`, `redacted_sha256` must match |
| `.docx` | yes | yes | yes | content | `redacted.docx` + `map.json`, `redacted_sha256` must match |
| `.xlsx` | yes | yes | yes | content | `redacted.xlsx` + `map.json`, `redacted_sha256` must match |
| `.png/.jpg/.jpeg/.tiff/.bmp` | `redact-scan` | **no restore** | via map | irreversible | Not restorable — derivative only |
| `.pptx/.html` | `redact-scan` or `parse` | **no restore** | via map | irreversible | Not restorable — derivative only |
| scanned `.pdf` | `redact-scan`（需 `[pdf]`+`[ocr]`） | **no restore** | via map | irreversible | Not restorable — derivative only |
| `.doc/.xls/.wps/.et/.dps/.pages/.numbers/.key` | **unsupported** | **unsupported** | **unsupported** | — | Convert to .docx/.xlsx/.pptx or PDF/image first |

**Verification semantics:**
- `byte` — restored file SHA-256 must equal original file SHA-256
- `content` — `extract_text(source) == extract_text(restored)` (not byte-level)
- `irreversible` — `pipeline: scan`, `restore_supported: false`, `best_effort: true` (OCR may miss/misrecognize)

## Model Determination (NER vs Regex)

The CLI supports two detection engines: **regex** (always available) and **NER** (requires local ONNX model).

**Reliable fallback: `--regex-only`.** Structured PII (phone, ID card, email, case number, social credit code, monetary amount) is handled deterministically by regex rules. No model is needed for this fallback.

**NER is optional best-effort.** When enabled, NER may detect person names, locations, organizations, and time expressions. However, NER results are **not a desensitization safety guarantee**:

- May miss company names (e.g., "某某科技有限公司")
- May miss address tail segments (e.g., door numbers)
- No MONEY entity (relies on regex)
- General-domain models, not trained on legal text
- Audit will mark NER runs with `best_effort` notice

**You must follow this flow—do not skip steps or pretend NER ran:**

1. Run `legal-desens ner-inspect`.
2. If the command is missing, the model is missing, or `self_test.passed` is false, run `bash scripts/install_with_model.sh` once from this skill/project root.
3. Run `legal-desens ner-inspect` again.
4. If `self_test.passed: true` → use regex+ner by omitting `--regex-only`.
5. If bootstrap fails or the user explicitly declines model install → use `--regex-only` and report that NER was unavailable.
6. In your final report, state whether this run used `regex-only` or `regex+ner`.

```bash
# Step 1: Check NER availability and self-test
legal-desens ner-inspect
# If command is not on PATH:
python3 -m legal_desens.cli ner-inspect

# If missing or self_test.passed=false, install CLI + GitHub Release model
bash scripts/install_with_model.sh

# Step 2a: NER available — run without --regex-only
legal-desens redact input.txt --level strict --out ... --map ... --audit ...

# Step 2b: NER unavailable — always pass --regex-only
legal-desens redact input.txt --level strict --regex-only --out ... --map ... --audit ...
```

**Never** omit `--regex-only` when NER has not been verified. The CLI will error clearly if you try to use NER without a valid model, but the agent must not reach that state.

For a fresh workstation, use the built-in bootstrap:

```bash
bash scripts/install_with_model.sh
```

This runs `pip install`, `legal-desens install-model --url ... --sha256 ...`, and `legal-desens ner-inspect`. If the model is unavailable or the hash is missing, report that clearly and use `--regex-only`.

Legacy/import-only mode remains available for users who already have an authorized local compatible model:

```bash
LEGAL_DESENS_MODEL_SRC=/path/to/model_dir bash scripts/install_with_model.sh
```

## Output Triple

Every `redact` command produces three files:

```
document.redacted.ext    — the desensitized document
document.map.json        — reversible mapping (SENSITIVE, see safety rules)
document.audit.json      — residual scan results + entity summary
```

Always pass `--out`, `--map`, and `--audit` to `redact`.

## Commands

### Redact

```bash
legal-desens redact <input.ext> \
  --level strict \
  [--regex-only] \
  --out <output.redacted.ext> \
  --map <output.map.json> \
  --audit <output.audit.json>
```

- `.txt` / `.md` / `.csv` / `.docx` / `.xlsx` accepted
- `--level strict` is the only supported level (activates all rules)
- `--model-dir <path>` overrides default NER model location

### Restore

```bash
legal-desens restore <redacted.ext> \
  --map <map.json> \
  --out <restored.ext>
```

- `.txt` / `.md` / `.csv` / `.docx` / `.xlsx` only
- Requires the exact `redacted.ext` + `map.json` pair produced by `redact`
- CLI verifies `redacted_sha256` before restoring; mismatch → error, no output
- CLI verifies `source_sha256` after restoring; mismatch → error

### Audit

```bash
legal-desens audit <redacted.ext> \
  --map <map.json> \
  --regex-only \
  --out <audit.json>
```

- Works on `.txt` / `.md` / `.csv` / `.docx` / `.xlsx`
- Produces residual scan (checks if sensitive patterns remain)

### NER Inspect

```bash
legal-desens ner-inspect [--model-dir <path>]
```

- Checks NER model availability, I/O signatures, and label mapping
- Must succeed before omitting `--regex-only`

### NER Spans

```bash
legal-desens ner-spans <input.txt> [--model-dir <path>] [--out spans.json]
```

- Runs NER on text and outputs detected spans as JSON (for debugging)

### Redact-Scan (irreversible, requires `[ocr]` extra; PDF also requires `[pdf]`)

```bash
legal-desens redact-scan <input.png|input.pdf> \
  --ocr rapidocr \
  [--regex-only] \
  --out <output.redacted.md> \
  --map <output.map.json> \
  --audit <output.audit.json>
```

- Accepts: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.pdf` (PDF requires `[pdf]` extra)
- For PDF input: renders each page to image → OCR → redact → per-page Markdown sections
- Requires: `pip install legal-desens[ocr]` (RapidOCR); for PDF also `pip install legal-desens[pdf]`
- Output: redacted Markdown + map (irreversible) + audit
- Map marks `pipeline: scan`, `verification: irreversible`, `restore_supported: false`, `best_effort: true`
- **No restore possible** — this produces derivative copies only
- Low-confidence OCR lines (< 0.7) appear as warnings in audit

### Parse (requires `[parse-docling]` extra)

```bash
legal-desens parse <input.pdf> \
  --parser docling \
  --out <output.parsed.md> \
  --meta <output.meta.json>
```

- Requires: `pip install legal-desens[parse-docling]` (Docling + PyTorch, heavy)
- Parses complex documents into Markdown
- Does NOT redact — combine with manual text redaction if needed

## Safety Rules

1. **Map is sensitive.** `map.json` contains original sensitive values and their positions. Never commit it, share it in chat, or expose it to unauthorized parties.
2. **Do not paste original sensitive content.** When reporting results, show entity types and counts—not the actual redacted values.
3. **Default to `--regex-only`.** Only enable NER after `ner-inspect` succeeds.
4. **Never fake NER.** If you did not run `ner-inspect` or it failed, you must use `--regex-only` and report `regex-only` in the audit.
5. **Do not force restore on mismatch.** If `redacted_sha256` in the map does not match the input file, restore will fail by design. Do not attempt workarounds.
6. **NER is best-effort, not a safety guarantee.** When NER is enabled, report "regex+ner (best-effort)" and note that company names and address fragments may be missed. Never claim NER coverage is complete.

## Per-Format Notes

### .txt
- Byte-level round trip: `redact → restore` produces a file identical to the original at the byte level.
- Handles UTF-8, BOM, CRLF, and trailing newlines correctly.

### .md
- Byte-level round trip (same as .txt): preserves Markdown structure, BOM, CRLF, trailing newlines.
- Treats .md as plain text with Markdown formatting — no special Markdown parsing.

### .csv
- Byte-level round trip: preserves dialect (delimiter, quotechar), encoding (BOM), newline, field quoting.
- Redacts only cell text content — CSV structure (commas, quotes, newlines) is preserved.
- Map includes CSV-specific locators: `type: csv`, `row`, `column`.

### .docx
- Content-level redact/restore on main body (`word/document.xml`).
- Cross-run entities within the same paragraph are supported.
- Cross-paragraph entities are not supported (written to audit warnings).
- Restore guarantees extracted text matches original, not byte-identical DOCX.

### .xlsx
- Content-level redact/restore on cell text (inline string / shared string).
- Formula cells are skipped with a warning in audit.
- Shared strings are never modified in-place (cells switched to inline string).

### .pdf (opt-in [pdf] extra, AGPL)
- PDF support is an opt-in `[pdf]` extra (PyMuPDF, AGPL licensed, local use only).
- Default core remains AGPL-free / commercial-safe — `pip install .` does not include PyMuPDF.
- Install with `pip install legal-desens[pdf]` or `pip install legal-desens[ocr,pdf]`.
- `redact-scan input.pdf` renders each page to image → OCR → redact → Markdown derivative.
- **Not reversible.** Map marks `restore_supported: false`, `best_effort: true`.
- Missing `[pdf]` extra → CLI returns a clear error with install guidance.
- Missing `[ocr]` extra → CLI returns a clear error (OCR is required for the pipeline).

### .pptx / .html
- Irreversible formats — use `redact-scan` or `parse` (requires `[ocr]` or `[parse-docling]` extra).
- CLI returns a clear error directing to the appropriate command.
- **Not reversible.** Derivative copies only.

### .png / .jpg / .jpeg / .tiff / .bmp
- Use `redact-scan` — irreversible OCR → redact → Markdown derivative.
- Requires `pip install legal-desens[ocr]` (RapidOCR).
- **Not reversible.** Map marks `restore_supported: false`, `best_effort: true`.
- OCR may miss or misrecognize characters — residual scan only covers recognized text.
- Low-confidence lines (< 0.7) are flagged in audit warnings.

### scanned PDF
- `redact-scan input.pdf` directly — renders pages to images → OCR → redact → Markdown derivative.
- Requires both `[pdf]` and `[ocr]` extras: `pip install legal-desens[pdf,ocr]`.
- Each page is rendered as a 200 DPI PNG, OCR'd independently, then merged into per-page Markdown sections.
- Map marks `restore_supported: false`, `best_effort: true` — **not reversible**.
- Keep only final redacted Markdown and the sensitive report; intermediate OCR/map/audit files belong in a local work directory and should be deleted after success.

## Batch Case Redaction

For folders of case materials, prefer the orchestrator instead of hand-written scripts:

```bash
legal-desens batch-redact-case \
  --input <case-folder> \
  --out <output-folder> \
  --profile labor
```

Default successful output contains only:

```text
final_redacted_md/
SENSITIVE_REDACTION_REPORT_DO_NOT_UPLOAD.md
run_manifest.json
```

Sensitive intermediate files are created under `_work_sensitive_do_not_upload/` and deleted on successful default runs. Use `--cleanup none` only for debugging; use `--cleanup archive` when the user asks to preserve map/audit/source index locally.

### .doc / .xls / .wps / .et / .dps / .pages / .numbers / .key
- Unsupported formats — CLI returns a clear error with conversion guidance.
- Convert to supported format first: .doc→.docx, .xls→.xlsx, others→.docx/.xlsx/.pptx or PDF/image.
