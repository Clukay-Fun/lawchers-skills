# Data Layout

## Home Directory Resolution

Default data root resolution:

1. `--home <path>`
2. `LAWCHERS_HOME`
3. `XDG_DATA_HOME/lawchers`
4. `~/.local/share/lawchers`
5. Windows fallback: `%LOCALAPPDATA%/lawchers`

## Suggested Layout

```text
$LAWCHERS_HOME/
  config.json
  logs/
  material/
    temp/
    cache/
  memory/
    memory.db
  kb/
    kb.db
    documents/
  workbench/
    contexts/
    outputs/
```

## Persistence Rules

- SQLite databases live under `$LAWCHERS_HOME/<feature>/<feature>.db`.
- JSON stores live under `$LAWCHERS_HOME/<feature>/*.json`.
- Logs live under `$LAWCHERS_HOME/logs/`.
- Temp workspaces live under `$LAWCHERS_HOME/material/temp/<timestamp>-<pid>-<random>/`.
- Normal CLI exits should clean their own temp workspace.
- Abandoned temp workspaces are cleaned by `material doctor --cleanup` or `lawchers doctor --cleanup`.
- Default temp TTL is 24 hours and may be overridden by `LAWCHERS_TEMP_TTL_HOURS` or config.

## Database Rules

- SQLite uses WAL mode by default.
- SQLite sets a `busy_timeout`, defaulting to 5000 ms.
- Write operations use transactions.
- Schema versions are stored in `schema_version` or `meta`.
- Migrations create timestamped backups before changing existing databases.
