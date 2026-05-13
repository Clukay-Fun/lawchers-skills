# Testing

## Test Stack

- Unit tests: `vitest`.
- CLI end-to-end tests: real child processes.
- Contract tests: stdout JSON, stderr JSON-lines logs, exit codes, paths, error codes.
- Provider tests: mocked by default, real provider tests optional/nightly with secrets.

## Local Test Layout

Test code and fixtures are local development assets. They are intentionally kept out of package directories and ignored by git.

```text
.local-tests/
  shared-core/
    tests/
  embedding-provider/
    tests/
  cli/
    tests/
  memory-cli/
    tests/
    fixtures/
```

Each local test project may symlink `src` back to its package source when that keeps imports simple:

```text
.local-tests/memory-cli/src -> ../../packages/cli/skills/memory-tools/scripts
```

Package directories should not commit `tests/` or `fixtures/` in the current lightweight development phase.

## Default Checks

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

`npm test` is configured to read `.local-tests/**/*.test.ts`.

## Coverage Targets

- `foundation` and `foundation/embedding-provider`: focus on contract stability, path behavior, config merging, and provider fallback.
- `lawchers` and skill scripts: prioritize command parsing, JSON output, stable errors, paths, concurrency, and migration behavior.
- OCR/provider behavior may use mocks in default CI.

## CI Matrix

Current tests are local-only. Before enabling CI, decide whether to commit a public test suite or generate test fixtures during CI setup.

Target matrix when CI is introduced:

- Node.js LTS.
- macOS, Linux, Windows.
- No provider keys in default tests.
- Optional provider tests enabled by secrets.
