# Agent Notes

This project builds an independent legal desensitization CLI and skill.

Read `/Users/clukay/Program/lawchers-skills/docs/HANDOFF.md` before implementation.

## Core Direction

- Route B: independently rebuilt engine.
- The `legal-desens` CLI is the sole capability core.
- The skill (SKILL.md) instructs agents how to call the CLI.
- MCP is deferred (006); do not introduce MCP dependencies.
- Do not implement frontend work unless explicitly asked.

## CLI Capabilities (as of 010)

- `legal-desens redact` — .txt / .md / .csv / .docx / .xlsx (reversible)
- `legal-desens restore` — .txt / .md / .csv / .docx / .xlsx (reversible)
- `legal-desens audit` — .txt / .md / .csv / .docx / .xlsx
- `legal-desens redact-scan` — image/scanned doc → OCR → redact → irreversible derivative (requires `[ocr]`)
- `legal-desens parse` — document → Markdown via Docling (requires `[parse-docling]`)
- `legal-desens ner-inspect` — check NER model availability
- `legal-desens ner-spans` — run NER and output spans (debug)

### Format Matrix (010)

**A: Core reversible (byte-level)**
- .txt, .md, .csv — byte-level round-trip (BOM, CRLF, newline, dialect preserved)

**A: Core reversible (content-level)**
- .docx, .xlsx — content-level round-trip (extracted text matches)

**B: Irreversible (route to 009)**
- .pdf, .png, .jpg, .jpeg, .tiff, .bmp, .pptx, .html — use `redact-scan` or `parse`

**C: Unsupported (conversion guidance)**
- .doc, .xls, .wps, .et, .dps, .pages, .numbers, .key — convert first

## Default Stack (commercial-safe)

- No AGPL dependencies (PyMuPDF removed in 008)
- Permissive-only: onnxruntime, tokenizers, lxml, python-docx, openpyxl

## Agent Decision Flow

1. Detect file extension → pick row from decision table in SKILL.md.
2. For any redact: run `ner-inspect` first to decide `--regex-only`.
3. Always pass `--out`, `--map`, `--audit` to `redact`.
4. For restore: verify `redacted_sha256` match (CLI does this, but agent should not force restore if mismatched).
5. For scan (images/scanned docs): use `redact-scan` — map is irreversible, no restore possible.
6. Report: state mode (regex-only or regex+ner), entity counts, verification result.

## Scan Pipeline (009) Notes

- `redact-scan` produces **irreversible** derivatives — `restore_supported: false`, `best_effort: true`.
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
