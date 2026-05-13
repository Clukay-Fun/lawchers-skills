# Memory Module

`memory-tools` is the first runnable skill script module in this repo. It is called through the unified `lawchers` CLI and gives agents a small local long-term memory store without requiring Obsidian, provider keys, or model configuration.

## What Works Now

- Local SQLite storage with WAL, foreign keys, and FTS5.
- `doctor`, `migrate`, `learn`, `recall`, `list`, `clear`, and `sync-obsidian`.
- Deterministic rule extractor for simple preferences, facts, and goals.
- Deduplication by content hash.
- Recall by recent memories plus FTS5 keyword search.
- JSON stdout contract and shared Lawchers error codes.

Not implemented yet:

- LLM extractor.
- Vector similarity recall.
- Obsidian bidirectional sync.
- Bridge integration.

## Install And Build

From the repository root:

```bash
npm install
npm run build
```

Link the unified CLI for local command-name usage:

```bash
npm link --workspace @lawchers/cli
lawchers memory doctor
```

## First Run

No config is required.

```bash
lawchers memory doctor
lawchers memory learn --user local --user-message "我喜欢轻量、可解释的开发工具"
lawchers memory recall --user local --query "开发工具偏好"
lawchers memory list --user local
```

If `lawchers` is not linked, replace it with:

```bash
node packages/cli/dist/src/bin.js
```

## Data Storage

By default, memory is stored only on the local machine.

Lawchers home resolution:

1. explicit `--home <path>`
2. `LAWCHERS_HOME`
3. Windows `%LOCALAPPDATA%/lawchers`
4. macOS `~/Library/Application Support/lawchers`
5. Linux/other `$XDG_DATA_HOME/lawchers`
6. fallback `~/.local/share/lawchers`

Memory database:

```text
$LAWCHERS_HOME/memory/memory.db
```

SQLite may also create:

```text
$LAWCHERS_HOME/memory/memory.db-wal
$LAWCHERS_HOME/memory/memory.db-shm
```

On macOS with no overrides, that means:

```text
~/Library/Application Support/lawchers/memory/memory.db
```

Use `--home` for isolated local testing:

```bash
lawchers memory learn --home /tmp/lawchers-mem-dev --user local --user-message "我偏好 JSON 输出"
```

## Obsidian

Obsidian is optional and not part of default storage.

If nothing is configured, memories stay in SQLite only. To export a Markdown snapshot:

```bash
lawchers memory sync-obsidian --user local --out "/path/to/obsidian/folder"
```

This creates `<safe-user>.memory.md` in the output folder. It does not read from Obsidian, merge notes back, or keep a background sync process.

## Extractor And Models

No segmentation model, embedding model, or LLM extractor is required.

Default extractor:

```json
{
  "memory": {
    "extractor": {
      "type": "rule",
      "confidenceThreshold": 0.5
    }
  }
}
```

Supported extractor types:

- `rule`: deterministic local rules for preferences, facts, and goals.
- `noop`: store conversations but extract no memory items.

Optional config can be placed in:

```text
$LAWCHERS_HOME/config.json
.lawchers/config.json
```

The legacy `~/.lawchers/config.json` path is not read in this lightweight version.

## Embedding Provider

The current CLI diagnoses embedding provider availability but does not require embeddings for recall. Missing or disabled embedding config is a warning, not a failure.

Default behavior with no `OPENAI_API_KEY`:

```text
PROVIDER_UNAVAILABLE: Embedding provider not available; recall uses FTS + recent only
```

To explicitly silence provider expectations during local-only use:

```json
{
  "providers": {
    "embedding": {
      "type": "disabled"
    }
  }
}
```

If an OpenAI-compatible provider is configured later:

```json
{
  "providers": {
    "embedding": {
      "type": "openai-compatible",
      "baseUrl": "https://api.openai.com/v1",
      "model": "text-embedding-3-small",
      "apiKeyEnv": "OPENAI_API_KEY"
    }
  }
}
```

Then set:

```bash
export OPENAI_API_KEY=...
```

## Command Reference

```bash
lawchers memory doctor [--home <path>] [--config-file <path>]
lawchers memory migrate [--dry-run] [--home <path>] [--config-file <path>]
lawchers memory learn --user <id> --user-message <text> [--assistant-message <text>] [--home <path>] [--config-file <path>]
lawchers memory recall --user <id> --query <text> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory list --user <id> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory clear --user <id> --confirm [--home <path>] [--config-file <path>]
lawchers memory sync-obsidian --user <id> --out <folder> [--home <path>] [--config-file <path>]
```

All commands print one JSON object to stdout.

## Codex Usage

Codex-facing guidance is in:

```text
packages/cli/skills/memory-tools/SKILL.md
```

That file explains when to call `lawchers memory`, when not to call it, the fallback behavior, and safety rules. It is the source to read before registering the skill in a plugin manifest.
