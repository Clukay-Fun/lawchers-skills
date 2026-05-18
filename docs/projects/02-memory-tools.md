# Project 2: Memory Module

## Status

First local version implemented and verified. It now runs through the unified `lawchers` CLI.

Implemented skill scripts:

```text
packages/cli/skills/memory-tools/scripts/
```

Agent guidance:

```text
packages/cli/skills/memory-tools/SKILL.md
```

## Goal

Provide lightweight local long-term memory skill scripts for agents, including learning, recall, listing, clearing, doctor checks, migrations, and explicit Markdown export.

## Implemented Commands

```bash
lawchers memory doctor [--home <path>] [--config-file <path>]
lawchers memory migrate [--dry-run] [--home <path>] [--config-file <path>]
lawchers memory learn --user <id> --user-message <text> [--assistant-message <text>] [--home <path>] [--config-file <path>]
lawchers memory recall --user <id> --query <text> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory list --user <id> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory clear --user <id> --confirm [--home <path>] [--config-file <path>]
lawchers memory sync-obsidian --user <id> --out <folder> [--home <path>] [--config-file <path>]
```

## Current Scope

- SQLite memory database at `$LAWCHERS_HOME/memory/memory.db`.
- Schema v1 with migrations.
- WAL, foreign keys, and `busy_timeout`.
- Deterministic conversation and memory content dedupe.
- Recent recall.
- FTS5 keyword recall.
- Memory extractor abstraction.
- Local deterministic `rule` extractor.
- `noop` extractor for raw conversation storage without memory extraction.
- Obsidian one-way Markdown export by explicit `--out` path.
- Recall block output format for prompt injection.
- Colocated `memory-tools` skill documentation.
- Static feature registry for `lawchers memory`.

## Deferred

- LLM extractor.
- Embedding similarity recall.
- Obsidian bidirectional sync.
- Bridge integration.
- `--extractor` command-line override.
- Remote sync.

The embedding provider is checked and diagnosed today, but missing or disabled embedding does not block recall. Current recall uses recent + FTS5 only.

## Non-Goals

- No Bridge `MemoryRuntimeModule`.
- No Bridge-specific system message injection timing.
- No platform session integration.
- No background service.
- No remote sync.

## Output Expectations

Recall returns structured JSON plus a ready-to-inject text block:

```json
{
  "ok": true,
  "result": {
    "memories": [],
    "recallBlock": ""
  },
  "warnings": []
}
```

All commands follow the shared Lawchers JSON result contract. stdout is always JSON.

## Acceptance Criteria

- `learn -> recall -> list -> clear -> doctor` works without provider keys.
- Duplicate submissions are ignored or reported deterministically.
- Recall works without provider keys using recent/FTS modes.
- Embedding status is diagnosed as `ok`, `disabled`, or `unavailable`.
- `doctor` reports home, DB, schema, FTS, extractor, and embedding readiness.
- `clear` requires `--confirm`.
- `sync-obsidian` sanitizes output filenames and writes only inside the requested output directory.

## Risks

- Low-quality memory extraction creating noisy persistent state.
- Overcoupling recall format to one agent.
- Mistaking one-way Obsidian export for live sync.
