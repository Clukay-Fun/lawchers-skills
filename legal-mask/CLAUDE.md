# Claude Code Notes

If the repo root contains `docs/HANDOFF.md`, follow its handoff rules first (local dev; `docs/` is not tracked in git).

## Constraints

- No git operations unless explicitly requested.
- No unrelated refactors.
- No real sensitive fixtures unless explicitly provided and authorized.
- CLI tests are the primary validation surface.
- Keep redaction maps, generated outputs, and model files out of git.
- Default stack is commercial-safe (no AGPL). PDF support is opt-in `[pdf]` extra (AGPL, local use only).

## Runtime Behavior

Runtime rules (profile selection, review triggering, safety, three-part report) live in `SKILL.md`. Do not restate them here. This file is for what NOT to do while editing the project.

When editing review/export code, test malformed decisions and source-map mismatches as well as a successful prepare → review → export flow with synthetic input. Runtime reporting requirements remain in `SKILL.md`.
