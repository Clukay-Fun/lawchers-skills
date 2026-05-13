# Error Codes

Error codes are stable API surface for agents. Add new codes intentionally and document them here.

## Shared

- `CONFIG_INVALID`: configuration exists but is not valid.
- `PROVIDER_UNAVAILABLE`: selected provider is missing or cannot be used.
- `IO_ERROR`: file or directory operation failed.
- `MISSING_FIELD`: required input is missing.
- `TIMEOUT`: command exceeded timeout.
- `INTERNAL_ERROR`: unexpected failure.

## Data And Migration

- `SCHEMA_UNSUPPORTED`: database schema cannot be read by this CLI version.
- `MIGRATION_FAILED`: migration did not complete.
- `LOCK_TIMEOUT`: file or database lock could not be acquired in time.

## Material

- `PATH_NOT_ALLOWED`: requested path is outside allowed roots.
- `ARCHIVE_UNSAFE`: archive failed safety checks.
- `FILE_TOO_LARGE`: file exceeds configured limits.
- `UNSUPPORTED_FILE_TYPE`: parser does not support the file type.
- `PARSE_FAILED`: parsing failed after fallback chain.

## Confidence And Safety

- `LOW_CONFIDENCE`: command refused to produce a write or final claim at low confidence.
- `CONFIRMATION_REQUIRED`: command requires explicit confirmation before proceeding.
- `UNSAFE_INPUT`: input violates safety constraints.
