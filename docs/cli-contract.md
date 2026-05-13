# CLI Contract

`lawchers` is the only official CLI entrypoint. Skill scripts register commands through the static feature registry instead of implementing independent CLI shells.

## Command Discovery

Agent skills should call:

```bash
lawchers <domain> <command> [flags]
```

Current implemented domain:

```bash
lawchers memory ...
```

## Stdout

Stdout must contain exactly one JSON result object.

Successful result:

```json
{
  "ok": true,
  "result": {},
  "warnings": []
}
```

Failed result:

```json
{
  "ok": false,
  "code": "MISSING_FIELD",
  "message": "Missing required field",
  "details": {}
}
```

## Stderr

Stderr may contain JSON-lines logs:

```json
{"ts":"2026-05-13T10:00:00.000Z","level":"info","msg":"opened database","pkg":"@lawchers/kb","event":"sqlite.open","traceId":"abc","details":{"database":"kb"}}
```

Logs must not contain API keys, full material text, or sensitive user content.

## Exit Codes

- `0`: `ok: true`.
- `2`: `ok: false` with `INVALID_INPUT`, `MISSING_FIELD`, or `CONFIG_INVALID`.
- `1`: other standard `ok: false` results.
- `70`: unexpected crash; stdout still contains a JSON error object.

## Common Flags

The CLI kernel owns these global flags:

```bash
--home <path>
--config-file <path>
--log-level error|warn|info|debug|trace
--trace-id <id>
```

stdout is always JSON.

## Unknown Commands

`--help` is not implemented in Phase 2. Unknown domains or commands return `INVALID_INPUT` with discovery details:

```json
{
  "ok": false,
  "code": "INVALID_INPUT",
  "message": "Unknown command: nope",
  "details": {
    "domain": "memory",
    "command": "nope",
    "availableCommands": ["doctor", "migrate", "learn", "recall", "list", "clear", "sync-obsidian"]
  }
}
```

## Path Rules

- Input paths may contain spaces.
- Returned paths must be absolute.
- Skills and docs must quote path examples.
- Symlinks must follow the security policy in `docs/security.md`.
