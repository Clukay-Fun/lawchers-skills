---
name: memory-tools
description: Use lawchers memory skill scripts to learn, recall, list, clear, diagnose, and export durable user memories.
---

# memory-tools

Use this skill when an agent needs local long-term memory for a user or workspace: recording stable preferences/facts/goals, recalling relevant memories before answering, listing what is stored, clearing local memory with confirmation, or exporting a Markdown snapshot.

Do not use it for legal knowledge-base ingestion, case evidence management, document parsing, remote sync, or secrets storage.

## Current State

- Skill scripts: `packages/cli/skills/memory-tools/scripts`
- Command: `lawchers memory`
- Runtime: Node.js `>=20` with npm
- Storage: local SQLite only
- Default recall: recent memories + FTS5 keyword search
- Obsidian: optional one-way Markdown export only
- Embedding: optional provider status check only; missing keys do not block recall
- Extractor: deterministic local `rule` extractor by default; no LLM or segmentation model required

The skill is repo-local until it is registered in `.claude-plugin/plugin.json`.

## Before Running

If the command is not globally linked, run through the built file from the repository root:

```bash
npm install
npm run build
npm link --workspace @lawchers/cli
lawchers memory doctor
```

## Data Location

Lawchers home resolution:

1. command `--home <path>`
2. `LAWCHERS_HOME`
3. Windows `%LOCALAPPDATA%/lawchers`
4. macOS `~/Library/Application Support/lawchers`
5. Linux/other `$XDG_DATA_HOME/lawchers`
6. fallback `~/.local/share/lawchers`

Memory DB path:

```text
$LAWCHERS_HOME/memory/memory.db
```

SQLite may also create `memory.db-wal` and `memory.db-shm`.

If nothing is configured, the CLI still works locally and creates the DB on first write or migration.

## Commands

stdout is always JSON.

```bash
lawchers memory doctor [--home <path>] [--config-file <path>]
lawchers memory migrate [--dry-run] [--home <path>] [--config-file <path>]
lawchers memory learn --user <id> --user-message <text> [--assistant-message <text>] [--home <path>] [--config-file <path>]
lawchers memory recall --user <id> --query <text> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory list --user <id> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory clear --user <id> --confirm [--home <path>] [--config-file <path>]
lawchers memory sync-obsidian --user <id> --out <folder> [--home <path>] [--config-file <path>]
```

## Suggested Agent Flow

1. Run `lawchers memory doctor` when first using this repo or when storage seems broken.
2. Run `lawchers memory recall --user <id> --query <current task>` before relying on prior user preferences.
3. Run `lawchers memory learn --user <id> --user-message <stable statement>` only for durable facts, preferences, or goals.
4. Run `lawchers memory list --user <id>` when auditing stored memory.
5. Run `lawchers memory clear --user <id> --confirm` only after explicit user confirmation.

## Config

No config is required. Optional config can live at `$LAWCHERS_HOME/config.json` or project `.lawchers/config.json`.

```json
{
  "memory": {
    "extractor": {
      "type": "rule",
      "confidenceThreshold": 0.5
    }
  },
  "providers": {
    "embedding": {
      "type": "disabled"
    }
  }
}
```

Set extractor `type` to `noop` to write raw conversations without extracting memory items.

If an OpenAI-compatible embedding provider is configured but its API key is missing, `recall` succeeds with a warning and uses recent + FTS5 only.

## Output Contract

Successful commands output one JSON object:

```json
{"ok":true,"result":{},"warnings":[]}
```

Failures output:

```json
{"ok":false,"code":"ERROR_CODE","message":"...","details":{}}
```

Treat `PROVIDER_DISABLED` and `PROVIDER_UNAVAILABLE` warnings during `recall` as non-blocking fallback signals.

## Safety

- Do not store API keys, passwords, full legal documents, or sensitive raw files as memory content.
- Learn only stable user-level preferences, facts, and goals.
- Prefer `recall` over reading the SQLite database directly.
- Do not write directly to Obsidian; use `lawchers memory sync-obsidian --out <folder>` for explicit export.
