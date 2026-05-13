# Project 2: Memory CLI

## Goal

Provide a local long-term memory CLI for agents, including learning, recall, listing, clearing, doctor checks, and Obsidian sync.

Future commands:

```bash
memory learn --user <id> --user-message <text> --assistant-message <text>
memory recall --user <id> --query <text>
memory list --user <id>
memory clear --user <id>
memory sync-obsidian
memory doctor
```

## Scope

- SQLite memory database.
- Schema version and migrations.
- Deterministic content hash or request ID dedupe.
- Recent recall.
- FTS5 keyword recall.
- Embedding recall.
- Memory extractor provider abstraction.
- Obsidian profile sync.
- Recall block output format for prompt injection.
- Colocated `memory-tools` skill documentation under `packages/memory-cli/skills/memory-tools/`.

## Non-Goals

- No Bridge `MemoryRuntimeModule`.
- No Bridge-specific system message injection timing.
- No platform session integration.
- No remote sync.

## Development Phases

1. Define memory record schema, migration strategy, and JSON output contract.
2. Implement `doctor`, `migrate --dry-run`, and `migrate`.
3. Implement `learn` as an atomic append with dedupe.
4. Implement `list` and `clear` with confirmation behavior.
5. Implement recent and FTS5 recall.
6. Add embedding recall through `embedding-provider`.
7. Add extractor provider abstraction.
8. Add Obsidian sync as an optional path-based integration.

## Output Expectations

Recall should return structured JSON plus a ready-to-inject text block:

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

## Acceptance Criteria

- Concurrent `learn` calls are atomic.
- Duplicate submissions are ignored or reported deterministically.
- Recall works without provider keys using recent/FTS modes.
- Embedding recall is optional and clearly diagnosed when unavailable.
- `doctor` reports DB, schema, provider, and Obsidian sync readiness.

## Risks

- Low-quality memory extraction creating noisy persistent state.
- Overcoupling recall format to one agent.
- Obsidian sync overwriting user notes unexpectedly.
