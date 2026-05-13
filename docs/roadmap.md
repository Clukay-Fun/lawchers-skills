# Roadmap

This roadmap follows the five-project sequence from the source planning note.

## Stage 0: Planning Scaffold

Status: complete.

Deliverables:

- Project folders.
- Skill placeholders colocated under the single CLI package.
- Development guidelines adapted for this repository.
- CLI contract, data layout, config, error, security, and testing docs.
- One development plan per first-wave project.

Non-goals at scaffold time:

- No runnable CLI.
- No package publishing setup.
- No copied Bridge code.
- No skill release manifest entries.

## Stage 1: Shared Foundations

Status: complete for local Phase 1 validation.

Foundation modules:

- `foundation`
- `foundation/embedding-provider`

Outcome:

- Stable JSON result/error protocol.
- Config source precedence.
- Provider configuration shape.
- Logging and trace contract.
- Embedding request and similarity helpers.

## Stage 2: Memory Skill Scripts

Status: first local version implemented.

Skill:

- `memory-tools`

Outcome:

- SQLite memory store.
- Recent and FTS5 recall.
- Embedding provider diagnosis; vector recall is deferred.
- Memory extraction provider abstraction.
- Optional one-way Obsidian Markdown export.
- Recall block format for agent prompt injection.
- Unified command entrypoint: `lawchers memory ...`.

## Stage 3: Material Tools

Skill:

- `material-tools`

Outcome:

- Local file and archive parsing.
- Markdown, plain text, and section output.
- Temp workspace lifecycle.
- OCR provider fallback contract.
- Strict file safety boundaries.

## Stage 4: Legal KB

Skill:

- `legal-kb`

Outcome:

- Local legal knowledge base.
- File and URL ingest.
- SQLite, FTS, and embedding search.
- Legal citation-oriented retrieval.
- Ask/search/docs/stats/doctor command set.

## Stage 5: Case Workbench

Skill:

- `case-workbench`

Outcome:

- Evidence extraction.
- Timeline construction.
- Evidence ledger and dossier rendering.
- Local case context store.
- Optional labor domain pack.

## Explicitly Deferred

- Platform webhooks.
- Feishu/Lark adapters.
- Bridge runtime integration.
- Session/window/queue lifecycle.
- Team accounts and cloud sync.
- Contract, invoice, and case ledger domain packs.
