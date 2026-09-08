# Agent Notes

Developer/maintainer constraints for `legal-desens`. Runtime use → read `SKILL.md`.

## Direction

- Route B: independently rebuilt engine.
- `legal-desens` CLI is the sole capability core; `SKILL.md` instructs agents how to call it.
- MCP is deferred; no MCP dependencies.
- No frontend unless explicitly asked.

## Capability Commitment Matrix

New formats/engines must land in one of these before being written into `SKILL.md`:

| Class | Members |
|---|---|
| A1 reversible byte | .txt, .md, .csv |
| A2 reversible content | .docx, .xlsx |
| B irreversible original-format copy | text-layer .pdf, images, scanned .pdf |
| C irreversible derived review material | parsed Markdown, audit/reports, batch outputs |
| D unsupported / experimental | .pptx, .html, second OCR/NER engines, legacy Office/WPS/iWork |

Promoting from D into A/B/C requires answering the six questions (see `references/known-gaps.md`).

## Default Stack

- No AGPL in default install: `onnxruntime`, `tokenizers`, `lxml`, `python-docx`, `openpyxl`.
- `[pdf]` extra (PyMuPDF) is AGPL, opt-in, local-use only.
- `[ocr]` extra (RapidOCR), `[parse-docling]` extra (Docling+PyTorch, heavy) are opt-in.

## Do Not

- Embed rules tables or model internals in skill files (CLI loads them).
- Pretend NER ran when it did not; claim NER found every name/company/address.
- Force restore on `redacted_sha256` mismatch.
- Expose map contents or original sensitive values in chat.
- Commit generated outputs, maps, or model files.
- Add new formats/engines without a plan doc answering the six questions.
- Extend `SKILL.md`'s scope past what CLI actually implements — put uncertain paths in `references/known-gaps.md`.

## Docs Layout

- `SKILL.md` — runtime usage (six sections; keep tight).
- `AGENTS.md` / `CLAUDE.md` — developer/maintainer constraints only.
- `references/install.md` — installation, wheelhouse, env vars, extras.
- `references/formats.md` — per-format implementation.
- `references/review.md` — decisions/entities/boxes schemas and review/export routing.
- `references/debug.md` — `ner-inspect`, `paths`, diagnostics, `INCOMPLETE_DO_NOT_USE`.
- `references/known-gaps.md` — unverified paths, legacy formats, OCR/NER limits, six-question gate.
- `references/optional-ner-models.md` — NER model candidates.
- `docs/plan/00X-*.md` — staged plans (not tracked in git).
