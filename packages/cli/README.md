# @lawchers/cli

Unified `lawchers` command shell.

Responsibilities:

- Route `lawchers <domain> <command>` calls through the static feature registry.
- Own global flags, context construction, JSON stdout, stderr logging, and exit codes.
- Run aggregate doctor checks with `lawchers doctor`.
- Reuse skill script registries directly rather than shelling out.

Implemented domain:

```bash
lawchers memory doctor
lawchers memory learn --user <id> --user-message <text>
lawchers memory recall --user <id> --query <text>
```

stdout is always one JSON object.
