# Claude Code Notes

If the repo root contains `docs/HANDOFF.md`, follow its handoff rules first (local dev convention; the `docs/` directory is not tracked in git, so it may be absent in a fresh clone).

## Constraints

- No git operations unless explicitly requested.
- No unrelated refactors.
- No real sensitive fixtures unless explicitly provided and authorized.
- Use CLI tests as the primary validation surface.
- Keep redaction maps and generated outputs out of git.
- Keep model files out of ordinary git history unless the user explicitly chooses a model distribution strategy.
- Default stack is commercial-safe (no AGPL). PDF support is opt-in `[pdf]` extra (AGPL, local use only).

## Before Running Commands

1. Read `SKILL.md` for the decision table and safety rules.
2. Run `legal-desens ner-inspect` before deciding whether to use `--regex-only`.
3. Always produce the output triple: redacted file + map.json + audit.json.

## Reporting

After completing a desensitization task, report:

- File format and which verb was used (redact / restore / audit)
- Mode: `regex-only` or `regex+ner` (and how NER availability was determined)
- Entity count and type distribution (from audit.json summary)
- Verification result (byte / content / residual-scan passed)
- Any warnings from audit.json
