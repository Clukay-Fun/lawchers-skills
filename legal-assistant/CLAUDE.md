# Claude Code Notes

## Constraints

- No git operations unless explicitly requested.
- No unrelated refactors.
- CLI tests are the primary validation surface: `python3 -m pytest tests/`.
- `config.yaml` (contains real paths / table tokens), `state/`, `journal/`, and weekly xlsx artifacts stay out of git.
- No real sensitive fixtures; synthesize invoice/contract test data via `tests/conftest.py`.
- Feishu access only through lark-cli (adapter: `scripts/lark.py`); do not add HTTP client dependencies or store any credentials in the repo.

## Before Running Commands

1. Read the decision table, confirmation protocol, and safety boundaries in `SKILL.md`.
2. On wake-up, run `legal-assistant journal` for recent context; check `pending` if there are pending items.
3. For environment issues, run `legal-assistant doctor --config config.yaml` first and fix findings one by one.
4. Confirm user intent before any operation that writes business tables (resolve / contract-commit / non-dry-run batch); use `--dry-run` for previews.

## Reporting

After completing a task, report:

- Which subcommand was used and whether it was a dry-run
- Counts of created / duplicate-skipped / pending / failed items (invoice-once, output-invoice-once)
- For pending items: the reason and candidate contract numbers (wait for the user's decision — never decide for them)
- A summary of what was recorded in the journal
- Any doctor findings and suggested fixes
