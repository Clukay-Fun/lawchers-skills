# Data Layout

## Home Directory Resolution

Default data root resolution:

1. Explicit `home` argument or future `--home <path>`
2. `LAWCHERS_HOME`
3. Windows: `%LOCALAPPDATA%/lawchers`
4. macOS: `~/Library/Application Support/lawchers`
5. Linux/other with `XDG_DATA_HOME`: `$XDG_DATA_HOME/lawchers`
6. Linux/other fallback: `~/.local/share/lawchers`

`resolveLawchersHome()` only resolves the path. It does not create the directory and does not check writability; setup/doctor commands own those checks.

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
