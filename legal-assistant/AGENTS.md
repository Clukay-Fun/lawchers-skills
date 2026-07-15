# Agent Notes

This project is a law-office daily-ops automation CLI + skill (inside the `lawchers-skills` repo, sibling of `legal-desensitizer`).

## Core Direction

- **Scripts do the work; the agent assists**: the `legal-assistant` CLI is the sole capability core, invoked headless by Windows Task Scheduler; the agent only handles fuzzy steps (contract-registration confirmation, outbound-invoice review), exceptions, and ad-hoc requests.
- All Feishu access goes through **lark-cli** shortcuts (`base +record-*` / `im +messages-send`); the adapter is `scripts/lark.py`. No hand-rolled HTTP clients, no credential management in this repo.
- Plan file: `docs/plan/001-v1-scope.md` (SSOT for v1 scope and slice breakdown).
- The Python code lives flat in `scripts/`, mapped to the `legal_assistant` package (see `pyproject.toml` package-dir).

## CLI Capabilities (as of 001)

- `legal-assistant doctor` — config / paths / lark-cli / dependency diagnostics
- `legal-assistant invoice-once` — inbound filing: invoice zip → parse/classify/write ledger/archive (invoice-number idempotent)
- `legal-assistant scan-once` — 7-category scan archiving (lock detection / no-overwrite / review fallback)
- `legal-assistant weekly-summary` — aggregate two tables into a cumulative snapshot → Feishu DM push (+ optional xlsx)
- `legal-assistant output-invoice-once` — outbound booking: outbound invoice PDF → unique contract match → write + write-back; ambiguity pends
- `legal-assistant pending / resolve` — outbound-invoice manual review protocol
- `legal-assistant contract-draft / contract-commit` — contract registration (nothing lands before confirmation)
- `legal-assistant journal` — recent operation log (agent memory)

## Key Invariants (read before changing code)

1. **Idempotency keys**: inbound filing = invoice number (remote set + local ledger, double dedup); outbound booking = invoice number; contract registration = contract number. Duplicates are rejected, never silently overwritten.
2. **When uncertain, don't write**: outbound-booking non-unique contract match, missing OCR fields, or suspected remote duplicate → `pending_review`, waiting for an explicit `resolve`.
3. **Write-back shares the main record's fate**: if the outbound-invoice main record is written but the contract-ledger write-back fails → `pending_review` (with `main_record_written`/`main_record_id`), PDF is not archived; a `resolve` retry only redoes the write-back and never duplicates the main record. `resolve` has identical semantics to the automatic path (main record + write-back + archive).
4. **dry-run contract**: `--dry-run` performs no Feishu writes and no file moves; reads are allowed (offline, inbound-filing dedup degrades to an empty set and notes it in the journal).
5. **File safety**: lock check before moving (locked → `skipped_locked`, retried next round); name collisions get `_1/_2` suffixes, never overwrite.
6. **Field mapping lives in config**: all field names for the three tables come from `config.yaml fields.*`; zero hard-coding. Contract-registration draft keys are translated through `DRAFT_KEY_MAP` + config before writing.
7. **Journal everything**: every business action appends to `journal/YYYY-MM-DD.md`; never log full ID numbers or contact details.

## Invoice PDF Parsing Notes

Real e-invoice text layers use a "labels first, values later in order" separated layout (see `tests/test_contracts.py::REAL_LAYOUT_TEXT`). Parsing anchors:

- Invoice number: inline "发票号码：N" first, else a standalone 20-digit number.
- Amount: inline "（小写）¥N" first; else the identity **total = pre-tax + tax** (the largest number that equals the sum of two others); finally the largest ¥-prefixed value.
- Counterparty name: the line immediately above a USCC (credit-code) line is a company name; after excluding `firm_name` (config), what remains is the counterparty.
- Inline regexes must never cross lines (`[ \t]`, not `\s`), or the separated layout pollutes matches.

Validated against a real sample set (6 invoices) with 6/6 fields correct; any change to parsing logic must rerun that validation.

## Constraints

- No git operations unless explicitly requested.
- Tests are the primary validation surface: `python3 -m pytest tests/` (FakeLark in-memory stub, never touches real Feishu).
- No real sensitive fixtures; all test data is synthesized (`tests/conftest.py::make_invoice_zip` / `make_raw_zip`).
- `config.yaml`, `state/`, `journal/`, and weekly-report artifacts stay out of git.
- The runtime target is **Windows** (Task Scheduler + PaddleOCR-VL hook); development happens on macOS, so platform-specific logic (file locking) must degrade gracefully on both.
- OCR goes through an external command hook (`scan.ocr_command`, `{file}` placeholder); no OCR engine is bundled in this project.
