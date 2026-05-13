# memory-tools

Agent-facing guidance lives in [SKILL.md](./SKILL.md).

This skill calls the local `lawchers memory` command. It is currently repo-local and is not registered in `.claude-plugin/plugin.json` yet.

Quick command surface:

```bash
lawchers memory doctor [--home <path>] [--config-file <path>]
lawchers memory migrate [--dry-run] [--home <path>] [--config-file <path>]
lawchers memory learn --user <id> --user-message <text> [--assistant-message <text>] [--home <path>] [--config-file <path>]
lawchers memory recall --user <id> --query <text> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory list --user <id> [--limit <n>] [--home <path>] [--config-file <path>]
lawchers memory clear --user <id> --confirm [--home <path>] [--config-file <path>]
lawchers memory sync-obsidian --user <id> --out <folder> [--home <path>] [--config-file <path>]
```
