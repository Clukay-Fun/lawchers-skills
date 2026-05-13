# Project 4: Legal KB

## Goal

Provide local legal knowledge base scripts for ingest, search, ask, stats, docs, and doctor flows.

Future commands:

```bash
lawchers legal-kb ingest <path>
lawchers legal-kb ingest-url <url>
lawchers legal-kb search <query>
lawchers legal-kb ask <question>
lawchers legal-kb docs
lawchers legal-kb stats
lawchers legal-kb doctor
```

## Scope

- File ingest through `material-tools` contracts.
- URL ingest with readable content extraction.
- Document list and document details.
- SQLite persistence with schema versions.
- FTS search.
- Embedding search.
- Legal citation and statute reference retrieval.
- Typed entries for case digest, practice note, and case reflow.
- Optional rerank provider.
- Colocated `legal-kb` skill documentation under `packages/cli/skills/legal-kb/`.

## Non-Goals

- No Bridge knowledge runtime module.
- No platform ingestion mode.
- No TTL, restoration, or chat session behavior.
- No remote hosted knowledge base.
- Obsidian export is deferred.

## Development Phases

1. Define DB schema, document model, chunk model, and migration rules.
2. Implement `doctor`, `stats`, `docs`, and migration checks.
3. Implement file ingest using material output.
4. Implement URL ingest.
5. Implement FTS search and citation-aware retrieval.
6. Add embedding search and optional rerank.
7. Implement `ask` response assembly with citations and low-confidence refusal.
8. Add fixtures and end-to-end CLI tests.

## Ask Behavior

`lawchers legal-kb ask` should prefer grounded answers with citations. If retrieval confidence is too low, it should refuse with a stable error instead of inventing authority.

## Acceptance Criteria

- Ingest is idempotent by content hash or source identity.
- Search works without provider keys using FTS.
- Embedding and rerank degrade gracefully.
- `ask` returns citations and confidence signals.
- `doctor` reports schema, document count, provider status, and index health.

## Risks

- Legal answers without sufficient grounding.
- Mixing source types without preserving provenance.
- URL ingest pulling unreadable or copyrighted boilerplate-heavy content.
