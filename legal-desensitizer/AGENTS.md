# Agent Notes

This project builds an independent legal desensitization CLI and skill.

If the repo root contains `docs/HANDOFF.md`, read it before implementation (local dev convention; `docs/` is not tracked in git and may be absent in a fresh clone).

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

### Capability Commitment Matrix

**A1: Core reversible (byte-level)**
- .txt, .md, .csv — byte-level round-trip (BOM, CRLF, newline, dialect preserved)

**A2: Core reversible (content-level)**
- .docx, .xlsx — content-level round-trip (extracted text matches)

**B: Irreversible original-format copy**
- text-layer .pdf — true redaction output PDF, no restore, verification by residual content scan
- .png, .jpg, .jpeg, .tiff, .bmp — white-box pixel redaction, no restore, verification by pixel output checks
- scanned .pdf — image-only white-box PDF derivative, no restore, verification by pixel output checks

**C: Irreversible derived review material**
- parsed Markdown, final reports, audit outputs — review/search artifacts only, no restore

**D: Unsupported or experimental**
- .pptx, .html, second OCR/NER engines — no production promise until promoted into A/B/C
- .doc, .xls, .wps, .et, .dps, .pages, .numbers, .key — convert first

Before adding support for a new format or engine, answer in the relevant plan and docs: reversible? map locator? audit scope? restore support? failure behavior? agent command?

## Default Stack (commercial-safe)

- No AGPL dependencies in default install (PyMuPDF removed in 008)
- Permissive-only: onnxruntime, tokenizers, lxml, python-docx, openpyxl
- PDF support via opt-in `[pdf]` extra (PyMuPDF, AGPL, local use only)

## Agent Decision Flow

1. Detect file extension → pick row from decision table in SKILL.md.
2. On a fresh machine: if `legal-desens ner-inspect` fails or `self_test.passed=false`, run `bash scripts/install_with_model.sh` from the skill/project root before falling back. This is an install convenience, not a detection guarantee.
3. For any redact: run `ner-inspect` first; use regex+ner only when `self_test.passed=true`, otherwise explicitly pass `--regex-only` and report the fallback.
4. Always pass `--out`, `--map`, `--audit` to `redact`.
5. For restore: verify `redacted_sha256` match (CLI does this, but agent should not force restore if mismatched).
6. For scan images/PDF: use `redact-scan` — map is irreversible, no restore possible. PDF requires `[pdf]`+`[ocr]` extras.
7. For case folders: prefer `batch-redact-case`; successful default output keeps final Markdown, sensitive report, and no-PII manifest while deleting `_work_sensitive_do_not_upload/`.
8. Report: state mode (regex-only or regex+ner), entity counts, verification result.

## Scan Pipeline (009/019) Notes

- `redact-scan` produces **irreversible** derivatives — `restore_supported: false`, `best_effort: true`, `verification: redacted-pixels`, `intermediate_markdown_file: ...`.
- "Irreversible" is the capability property; `redacted-pixels` is the verification mode.
- PDF input supported via opt-in `[pdf]` extra (AGPL). Each page rendered to 200 DPI PNG → OCR → redact → image-only PDF + per-page Markdown sections.
- Scanned PDF output does not preserve the source PDF text layer, structure tree, bookmarks, form semantics, or attachments.
- Missing `[pdf]` or `[ocr]` extra → clear error with install guidance, no silent skip.
- OCR may miss/misrecognize characters — this is expected. The `best_effort` flag in map/audit documents this.
- Low-confidence OCR lines (< 0.7) appear as warnings in audit.
- `parse` command requires `[parse-docling]` extra (heavy, PyTorch). Do not call without verifying extra is installed.

## NER Boundary

- Bootstrap scripts may install a local NER model by default, but that only prepares an enhancement engine.
- NER is best-effort recall enhancement, never a complete detection guarantee.
- Even when `ner-inspect` passes, do not claim all names, companies, addresses, or locations were found.
- If `ner-inspect` fails, report it and use `--regex-only`; never pretend regex+ner ran.

## Do Not

- Embed rules tables or model details in skill files (CLI loads them).
- Pretend NER ran when it did not.
- Claim NER found every name/company/address/location.
- Force restore when map and file are mismatched.
- Expose map contents or original sensitive values in chat.
- Commit generated outputs, maps, or model files.
