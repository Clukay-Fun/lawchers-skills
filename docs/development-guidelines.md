# Development Guidelines

These guidelines adapt the Bridge development notes for this new repository.

## Boundary

- Rebuild reusable capabilities; do not move or copy Bridge runtime code.
- Use Bridge only as a reference for responsibilities, command shape, edge cases, and tests.
- Keep the first wave independent from Bridge sessions, cards, queues, callbacks, permission prompts, and runtime modules.
- Prefer local deterministic CLI behavior over platform-specific adapters.
- Keep all CLI stdout parseable JSON. Send logs to stderr as JSON lines.

## Architecture

- Put cross-cutting contracts in `shared-core`.
- Put persistence primitives in `local-store`.
- Put model/provider adapters behind explicit provider abstractions.
- Keep domain logic out of the aggregate `packages/cli` entrypoint.
- Do not make a business feature depend on another feature's internal state files.
- Use SQLite WAL, transactions, and busy timeouts for concurrent writes.
- Use lock files and atomic rename for JSON stores.

## Skill Rules

- A skill explains when and how to call the CLI; it must not hide business state.
- Skills are colocated under the package that owns the CLI they call, for example `packages/kb-cli/skills/legal-kb/`.
- A released skill must list primary and standalone CLI commands.
- A released skill must describe inputs, output JSON, common error codes, low-confidence handling, and setup failure handling.
- Draft, in-progress, personal, and deprecated skills must not enter `.claude-plugin/plugin.json`.
- Skills should first try `lawchers`, then the standalone command, then guide users to setup or `npx -y @lawchers/cli`.

## File And Material Handling

- Treat local absolute paths as explicit user-provided material only after validating existence and type.
- File upload, local path, and archive extraction should all converge into the same material context shape.
- Archive extraction must block zip-slip and enforce size, count, file type, and nesting limits.
- OCR and parser subprocesses must have timeouts.
- Logs must not include API keys, full document text, or sensitive user content.

## Write Operations

Write-capable commands must provide:

- Confirmation behavior where destructive or irreversible.
- Low-confidence refusal.
- Missing-field feedback.
- Stable error codes.
- Trace IDs for diagnosis.

## Docs

- Keep long design notes in `docs/`.
- Keep implementation plans in `docs/projects/`.
- Update related docs in the same PR when changing CLI output, config, data layout, error codes, security boundaries, or test strategy.
- Do not put temporary task notes, personal preferences, or unverified guesses into long-lived docs.

## Git And PR Hygiene

- Check `git status --short` before edits.
- Do not revert user changes.
- Keep PRs to one clear theme.
- Do not mix cleanup, documentation reshuffling, refactors, and behavior changes unless the plan explicitly calls for it.
- Before publishing work, record commands actually run and explain checks not run.

## Verification Expectations

Start with the narrowest relevant check, then expand by risk:

```bash
npm run lint
npm run typecheck
npm test
npm run test:cli
npm run build
```

Provider tests that require secrets should be optional and separated from default CI.
