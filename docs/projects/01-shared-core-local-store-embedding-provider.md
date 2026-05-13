# Project 1: CLI Foundation / Embedding Provider

## Status

Phase 1 foundation modules are locally verified inside `@lawchers/cli`. Skill scripts build on this shared foundation.

## Goal

Build the horizontal foundation used by every later skill script.

Modules:

- `packages/cli/src/foundation`
- `packages/cli/src/foundation/embedding-provider`

## Scope

`foundation`:

- Unified result/error types.
- Stable error codes.
- Config resolution.
- Lightweight stderr JSON-lines logger.
- Trace IDs and observability event shape.

`embedding-provider`:

- OpenAI-compatible embedding request adapter.
- Provider config validation.
- Cosine similarity.
- Test doubles for provider-free CI.

## Non-Goals

- No Bridge pending interaction manager.
- No session recovery.
- No TTL card semantics.
- No feature-specific database schema.
- No business commands.

## Development Phases

1. Define TypeScript contracts for result, error, logger, config, and provider config.
2. Implement config source precedence and doctor helpers.
3. Implement embedding provider adapter and similarity helpers.
4. Add foundation-level tests and cross-module contract tests.

## Key Contracts

- Stdout-facing result shapes follow `docs/cli-contract.md`.
- Config follows `docs/config.md`.
- Data layout follows `docs/data-layout.md`.
- Error codes are documented in `docs/error-codes.md`.
- Runtime is Node.js `>=20` with npm; Bun and Deno are not supported in Phase 1.
- Logger fields are fixed as `ts`, `level`, `msg`, `pkg`, `event`, `traceId?`, `details?`.
- Public APIs are exported only through `packages/cli/src/foundation/index.ts`.

## Acceptance Criteria

- Every helper is usable without Bridge runtime.
- Embedding tests can pass without real provider keys.
- Public exports are small and documented.
- Provider disabled state is distinct from provider unavailable state.

## Risks

- Over-abstracting before additional skill scripts exist.
- Accidentally importing feature-specific behavior into foundation modules.
- Logging sensitive content from provider payloads.
