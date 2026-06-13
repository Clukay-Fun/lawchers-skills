# Agent Notes

This project builds an independent legal desensitization CLI and skill.

Read `/Users/clukay/Program/lawchers-skills/docs/HANDOFF.md` before implementation.

## Core Direction

- Route B: independently rebuilt engine.
- The `legal-desens` CLI is the sole capability core.
- The skill (SKILL.md) instructs agents how to call the CLI.
- MCP is deferred (006); do not introduce MCP dependencies.
- Do not implement frontend work unless explicitly asked.

## CLI Capabilities (as of 019)

- `legal-desens redact` — .txt / .md / .csv / .docx / .xlsx (reversible)
- `legal-desens restore` — .txt / .md / .csv / .docx / .xlsx (reversible)
- `legal-desens audit` — .txt / .md / .csv / .docx / .xlsx
- `legal-desens redact-scan` — image/PDF → OCR → redact → irreversible derivative (requires `[ocr]`; PDF also requires `[pdf]`)
- `legal-desens parse` — document → Markdown via Docling (requires `[parse-docling]`)
- `legal-desens ner-inspect` — check NER model availability
- `legal-desens ner-spans` — run NER and output spans (debug)

### Format Matrix (019)

**A: Core reversible (byte-level)**
- .txt, .md, .csv — byte-level round-trip (BOM, CRLF, newline, dialect preserved)

**A: Core reversible (content-level)**
- .docx, .xlsx — content-level round-trip (extracted text matches)

**B: Irreversible (route to 009)**
- .png, .jpg, .jpeg, .tiff, .bmp, .pptx, .html — use `redact-scan` or `parse`
- .pdf — use `redact-scan` (requires `[pdf]`+`[ocr]` extras, AGPL opt-in)

**C: Unsupported (conversion guidance)**
- .doc, .xls, .wps, .et, .dps, .pages, .numbers, .key — convert first

## Default Stack (commercial-safe)

- No AGPL dependencies in default install (PyMuPDF removed in 008)
- Permissive-only: onnxruntime, tokenizers, lxml, python-docx, openpyxl
- PDF support via opt-in `[pdf]` extra (PyMuPDF, AGPL, local use only)

## Agent Decision Flow

1. Detect file extension → pick row from decision table in SKILL.md.
2. On a fresh machine: if `legal-desens ner-inspect` fails or `self_test.passed=false`, run `bash scripts/install_with_model.sh` from the skill/project root before falling back.
3. For any redact: run `ner-inspect` first; use regex+ner only when `self_test.passed=true`, otherwise explicitly pass `--regex-only`.
4. Always pass `--out`, `--map`, `--audit` to `redact`.
5. For restore: verify `redacted_sha256` match (CLI does this, but agent should not force restore if mismatched).
6. For scan images/PDF: use `redact-scan` — map is irreversible, no restore possible. PDF requires `[pdf]`+`[ocr]` extras.
7. For case folders: prefer `batch-redact-case`; successful default output keeps final Markdown, sensitive report, and no-PII manifest while deleting `_work_sensitive_do_not_upload/`.
8. Report: state mode (regex-only or regex+ner), entity counts, verification result.

## Scan Pipeline (009/019) Notes

- `redact-scan` produces **irreversible** derivatives — `restore_supported: false`, `best_effort: true`.
- PDF input supported via opt-in `[pdf]` extra (AGPL). Each page rendered to 200 DPI PNG → OCR → redact → per-page Markdown sections.
- Missing `[pdf]` or `[ocr]` extra → clear error with install guidance, no silent skip.
- OCR may miss/misrecognize characters — this is expected. The `best_effort` flag in map/audit documents this.
- Low-confidence OCR lines (< 0.7) appear as warnings in audit.
- Map schema: `pipeline: scan`, `verification: irreversible`, `restore_supported: false`, `best_effort: true`.
- `parse` command requires `[parse-docling]` extra (heavy, PyTorch). Do not call without verifying extra is installed.

## Do Not

- Embed rules tables or model details in skill files (CLI loads them).
- Pretend NER ran when it did not.
- Force restore when map and file are mismatched.
- Expose map contents or original sensitive values in chat.
- Commit generated outputs, maps, or model files.
