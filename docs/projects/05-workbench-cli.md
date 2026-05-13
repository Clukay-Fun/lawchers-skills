# Project 5: Case Workbench

## Goal

Provide local case workbench scripts for evidence, timelines, dossiers, and optional labor-domain analysis.

Future commands:

```bash
lawchers case-workbench evidence-extract <path>
lawchers case-workbench timeline <json>
lawchers case-workbench render <json>
lawchers case-workbench dossier <folder>
lawchers case-workbench labor analyze <folder>
```

## Scope

- Material evidence extraction.
- Timeline construction.
- Evidence ledger as JSON or Markdown.
- Workbench Markdown rendering.
- Local case context store.
- Labor dispute analysis as an optional domain pack.
- Colocated `case-workbench` skill documentation under `packages/cli/skills/case-workbench/`.

## Non-Goals

- No platform document publishing.
- No external ledger adapter.
- No visual whiteboard adapter.
- No Bridge case workbench runtime module.
- Labor is optional, not the default path.

## Development Phases

1. Define case context, evidence item, timeline event, and render schemas.
2. Implement local case context store.
3. Implement evidence extraction on top of material output.
4. Implement timeline building with explainable confidence.
5. Implement ledger and workbench Markdown rendering.
6. Implement dossier generation for a folder.
7. Add optional `labor` domain pack after generic workbench behavior stabilizes.
8. Add fixtures and scenario tests.

## Safety And Confidence

- Structured extraction should be deterministic where possible.
- LLM repair may fill missing fields but must not rewrite confirmed fields.
- Low-confidence fields must be marked or refused.
- Writes must be traceable to source material locations.

## Acceptance Criteria

- Evidence items preserve source references.
- Timeline output is stable and testable.
- Rendered Markdown is usable without platform-specific formatting.
- Labor analysis can be installed or enabled without becoming a hard dependency.
- `doctor` reports store and provider readiness when added.

## Risks

- Blending business domain assumptions into generic workbench logic.
- Producing authoritative-looking timelines from weak extraction.
- Letting optional labor features drive the core data model too early.
