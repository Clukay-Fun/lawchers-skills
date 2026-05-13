# Testing

## Test Stack

- Unit tests: `vitest`.
- CLI end-to-end tests: real child processes.
- Contract tests: stdout JSON, stderr JSON-lines logs, exit codes, paths, error codes.
- Provider tests: mocked by default, real provider tests optional/nightly with secrets.

## Fixture Layout

```text
packages/material-cli/fixtures/
  sample.txt
  sample.docx
  sample.pdf
  sample-image.png
  sample.zip
packages/memory-cli/fixtures/
  conversation.jsonl
packages/kb-cli/fixtures/
  statute.txt
  case-digest.md
packages/workbench-cli/fixtures/
  evidence-folder/
  timeline.json
```

## Default Checks

```bash
npm run lint
npm run typecheck
npm test
npm run test:cli
npm run build
```

## Coverage Targets

- `shared-core`, `local-store`, and `embedding-provider`: target 80%+ once implemented.
- CLI packages: prioritize command parsing, JSON output, stable errors, paths, concurrency, and migration behavior.
- OCR/provider behavior may use mocks in default CI.

## CI Matrix

- Node.js LTS.
- macOS, Linux, Windows.
- No provider keys in default tests.
- Optional provider tests enabled by secrets.
