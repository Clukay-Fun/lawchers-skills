# Roadmap

This roadmap follows the five-project sequence from the source planning note.

## Stage 0: Planning Scaffold

Status: current.

Deliverables:

- Project folders.
- Skill placeholders colocated with their owning CLI packages.
- Development guidelines adapted for this repository.
- CLI contract, data layout, config, error, security, and testing docs.
- One development plan per first-wave project.

Non-goals:

- No runnable CLI.
- No package publishing setup.
- No copied Bridge code.
- No skill release manifest entries.

## Stage 1: Shared Foundations

Projects:

- `shared-core`
- `local-store`
- `embedding-provider`

Outcome:

- Stable JSON result/error protocol.
- Config source precedence.
- Provider configuration shape.
- Logging and trace contract.
- Safe local persistence primitives.
- Embedding request and similarity helpers.

## Stage 2: Memory CLI

Project:

- `memory-cli`

Outcome:

- SQLite memory store.
- Recent, FTS5, and embedding recall.
- Memory extraction provider abstraction.
- Obsidian profile sync.
- Recall block format for agent prompt injection.

## Stage 3: Material CLI

Project:

- `material-cli`

Outcome:

- Local file and archive parsing.
- Markdown, plain text, and section output.
- Temp workspace lifecycle.
- OCR provider fallback contract.
- Strict file safety boundaries.

## Stage 4: KB CLI

Project:

- `kb-cli`

Outcome:

- Local legal knowledge base.
- File and URL ingest.
- SQLite, FTS, and embedding search.
- Legal citation-oriented retrieval.
- Ask/search/docs/stats/doctor command set.

## Stage 5: Workbench CLI

Project:

- `workbench-cli`

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
