# CLI Contract

All first-wave CLIs share one contract.

## Command Discovery

Agent skills should try commands in this order:

1. `lawchers <feature> ...`
2. Standalone command such as `memory`, `material`, `kb`, or `workbench`
3. `npx -y @lawchers/cli ...`

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

- `0`: success.
- Non-zero: failure. Stdout still contains the error JSON object.

## Common Flags

Every CLI should support:

```bash
--home <path>
--json
--log-level error|warn|info|debug|trace
--trace-id <id>
--timeout-ms <number>
```

## Path Rules

- Input paths may contain spaces.
- Returned paths must be absolute.
- Skills and docs must quote path examples.
- Symlinks must follow the security policy in `docs/security.md`.
