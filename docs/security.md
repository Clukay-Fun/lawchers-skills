# Security

## Local File Access

- CLIs may read only user-explicit local paths by default.
- `LAWCHERS_ALLOWED_ROOTS` or config may restrict readable roots.
- Symlinks that resolve outside allowed roots are not followed by default.
- Returned paths must be absolute for auditability.

## Archive Handling

Archive extraction must:

- Block zip-slip.
- Limit total expanded size.
- Limit file count.
- Limit single-file size.
- Limit nesting depth.
- Skip hidden files by default.
- Skip executables, system directories, and unknown binaries by default.

## Provider Calls

- Do not log API keys.
- Do not log full document text.
- Do not pass unnecessary sensitive environment variables to parser/OCR subprocesses.
- Make provider uploads explicit in logs by provider type, not by content.

## Write Operations

Destructive or externally visible writes require confirmation unless a documented noninteractive flag is provided.

Low-confidence writes must refuse with a stable error before guessing; add a dedicated error code only when the first implementation needs it.

## Sensitive Data

This project should not implement team accounts, cloud sync, or remote hosted storage in the first wave.
