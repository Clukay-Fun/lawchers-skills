---
name: legal-desensitizer
description: Redact, restore, and audit sensitive information in Chinese legal documents using the local legal-desens CLI. Supports .txt/.md/.csv (byte-level), .docx/.xlsx (content-level), images/scanned docs via OCR (irreversible). PDF is not supported in the commercial-safe core. Use when a user asks to desensitize legal documents, generate redaction maps, restore redacted documents, or audit residual sensitive data.
---

# Legal Desensitizer

Use the local `legal-desens` CLI for legal document redaction, restoration, and audit. The CLI is the sole capability core—this skill instructs agents how to call it correctly.

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
| scanned `.pdf` | `redact-scan` | **no restore** | via map | irreversible | Not restorable — derivative only |
| `.doc/.xls/.wps/.et/.dps/.pages/.numbers/.key` | **unsupported** | **unsupported** | **unsupported** | — | Convert to .docx/.xlsx/.pptx or PDF/image first |

**Verification semantics:**
- `byte` — restored file SHA-256 must equal original file SHA-256
- `content` — `extract_text(source) == extract_text(restored)` (not byte-level)
- `irreversible` — `pipeline: scan`, `restore_supported: false`, `best_effort: true` (OCR may miss/misrecognize)

## Model Determination (NER vs Regex)

The CLI supports two detection engines: **regex** (always available) and **NER** (requires local ONNX model).

**Default mode: `--regex-only` is the reliable core.** Structured PII (phone, ID card, email, case number, social credit code, monetary amount) is handled deterministically by regex rules. No model is needed or downloaded.

**NER is optional best-effort.** When enabled, NER may detect person names, locations, organizations, and time expressions. However, NER results are **not a desensitization safety guarantee**:

- May miss company names (e.g., "某某科技有限公司")
- May miss address tail segments (e.g., door numbers)
- No MONEY entity (relies on regex)
- General-domain models, not trained on legal text
- Audit will mark NER runs with `best_effort` notice

**You must follow this flow—do not skip steps or pretend NER ran:**

1. Run `legal-desens ner-inspect` to check if the NER model is available.
2. If `ner-inspect` succeeds → you may omit `--regex-only` (enables regex+ner).
3. If `ner-inspect` fails, errors, or model path is unknown → **must** pass `--regex-only`.
4. In your final report, state whether this run used `regex-only` or `regex+ner`.

```bash
# Step 1: Check NER availability
legal-desens ner-inspect

# Step 2a: NER available — run without --regex-only
legal-desens redact input.txt --level strict --out ... --map ... --audit ...

# Step 2b: NER unavailable — always pass --regex-only
legal-desens redact input.txt --level strict --regex-only --out ... --map ... --audit ...
```

**Never** omit `--regex-only` when NER has not been verified. The CLI will error clearly if you try to use NER without a valid model, but the agent must not reach that state.

For a fresh workstation, prefer installing the CLI and NER model from a GitHub Release Asset:

```bash
LEGAL_DESENS_MODEL_URL="https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
LEGAL_DESENS_MODEL_SHA256="d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703" \
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

### Redact-Scan (irreversible, requires `[ocr]` extra)

```bash
legal-desens redact-scan <input.png> \
  --ocr rapidocr \
  [--regex-only] \
  --out <output.redacted.md> \
  --map <output.map.json> \
  --audit <output.audit.json>
```

- Accepts: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, scanned `.pdf`
- Requires: `pip install legal-desens[ocr]` (RapidOCR, lightweight ONNX)
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

### .pdf (text PDF — unsupported in core)
- Text PDF is not supported in the commercial-safe core (PyMuPDF was removed due to AGPL licensing).
- CLI will return a clear unsupported error with non-zero exit code.
- Use `redact-scan` for scanned/image PDFs (requires `[ocr]` extra).
- Use `parse` for complex PDFs (requires `[parse-docling]` extra).

### .pptx / .html
- Irreversible formats — use `redact-scan` or `parse` (requires `[ocr]` or `[parse-docling]` extra).
- CLI returns a clear error directing to the appropriate command.
- **Not reversible.** Derivative copies only.

### .png / .jpg / .jpeg / .tiff / .bmp / scanned PDF
- Use `redact-scan` — irreversible OCR → redact → Markdown derivative.
- Requires `pip install legal-desens[ocr]` (RapidOCR).
- **Not reversible.** Map marks `restore_supported: false`, `best_effort: true`.
- OCR may miss or misrecognize characters — residual scan only covers recognized text.
- Low-confidence lines (< 0.7) are flagged in audit warnings.

### .doc / .xls / .wps / .et / .dps / .pages / .numbers / .key
- Unsupported formats — CLI returns a clear error with conversion guidance.
- Convert to supported format first: .doc→.docx, .xls→.xlsx, others→.docx/.xlsx/.pptx or PDF/image.
