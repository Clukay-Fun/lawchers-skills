# lawchers-skills

`lawchers-skills` is a planned monorepo for reusable agent skills and local CLIs for document, memory, legal knowledge, and case workbench workflows.

This repository is currently in planning/scaffolding stage. It does not yet contain runnable CLI implementations.

## Positioning

The project will rebuild a set of `skill + CLI` capabilities for direct use by agents such as Codex, Claude, and OpenCode:

```text
agent / codex / opencode
  -> skill: intent routing, usage policy, prompt constraints
  -> cli: deterministic execution, local file/DB operations, JSON output
  -> providers/storage: local files, SQLite, embeddings, Obsidian
```

Bridge is used only as a reference for capability boundaries, data shape, product experience, command surfaces, and test scenarios. This repository must not copy Bridge runtime code, sessions, cards, queues, callbacks, or platform adapters.

## First Projects

The first implementation wave is split into five project plans:

1. [Shared Core / Local Store / Embedding Provider](./docs/projects/01-shared-core-local-store-embedding-provider.md)
2. [Memory CLI](./docs/projects/02-memory-cli.md)
3. [Material CLI](./docs/projects/03-material-cli.md)
4. [KB CLI](./docs/projects/04-kb-cli.md)
5. [Workbench CLI](./docs/projects/05-workbench-cli.md)

## Repository Map

- `packages/cli/`: future aggregate `lawchers` command.
- `packages/shared-core/`: future result protocol, config, errors, logging, observability.
- `packages/local-store/`: future JSON store, debounced persistence, file locking.
- `packages/embedding-provider/`: future OpenAI-compatible embeddings and similarity helpers.
- `packages/memory-cli/`: future long-term memory CLI.
- `packages/material-cli/`: future local material parsing CLI.
- `packages/kb-cli/`: future legal knowledge base CLI.
- `packages/workbench-cli/`: future evidence, timeline, dossier, and optional labor workflows.
- `packages/*/skills/`: future agent skills colocated with their owning CLI package.
- `docs/`: contracts, development guidelines, testing strategy, and project plans.

## Skill Ownership

Skills live next to the CLI package they call:

- `packages/cli/skills/setup-lawchers-skills/`: setup and global doctor workflow.
- `packages/material-cli/skills/material-tools/`: material parsing workflow.
- `packages/memory-cli/skills/memory-tools/`: long-term memory workflow.
- `packages/kb-cli/skills/legal-kb/`: legal knowledge base workflow.
- `packages/workbench-cli/skills/case-workbench/`: evidence, timeline, dossier, and case workbench workflow.

This keeps each skill's command contract, fixtures, implementation, and tests in one package boundary.

## Planning Docs

- [Roadmap](./docs/roadmap.md)
- [Development Guidelines](./docs/development-guidelines.md)
- [CLI Contract](./docs/cli-contract.md)
- [Config](./docs/config.md)
- [Data Layout](./docs/data-layout.md)
- [Error Codes](./docs/error-codes.md)
- [Security](./docs/security.md)
- [Testing](./docs/testing.md)

## Release Rule

No skill is considered released until it is listed in both:

- `README.md`
- `.claude-plugin/plugin.json`

Draft, personal, in-progress, and deprecated skills must not appear in the plugin manifest. During planning, the manifest remains empty.
