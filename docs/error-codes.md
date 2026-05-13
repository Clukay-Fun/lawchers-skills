# Error Codes

Error codes are stable API surface for agents. Phase 1 freezes the shared set below. Feature packages must reuse these codes; adding a new code requires updating `@lawchers/shared-core` and this document first.

## Phase 1 Shared Set

- `MISSING_FIELD`: required input is missing.
- `INVALID_INPUT`: input is present but invalid for the requested operation.
- `CONFIG_INVALID`: configuration exists but is not valid.
- `IO_ERROR`: file or directory operation failed.
- `LOCK_TIMEOUT`: file or database lock could not be acquired in time.
- `PROVIDER_UNAVAILABLE`: selected provider is missing, misconfigured, unreachable, or returned an invalid response.
- `PROVIDER_DISABLED`: selected provider is intentionally disabled.
- `TIMEOUT`: command or provider operation exceeded timeout.
- `PARSE_FAILED`: parsing failed after fallback chain.
- `LOW_CONFIDENCE`: command refused to produce a write or final claim at low confidence.
- `UNKNOWN`: unexpected failure.

## Diagnostics

Errors default to stack-free JSON. Diagnostic layers may include stack details only when `LAWCHERS_DEBUG=1`.
