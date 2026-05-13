# Project 1: Shared Core / Local Store / Embedding Provider

## Status

Phase 1 foundation packages are locally verified at `0.1.0`. Business CLIs have not started.

## Goal

Build the horizontal foundation used by every later CLI package.

Packages:

- `packages/shared-core`
- `packages/local-store`
- `packages/embedding-provider`

## Scope

`shared-core`:

- Unified result/error types.
- Stable error codes.
- Config resolution.
- Lightweight stderr JSON-lines logger.
- Trace IDs and observability event shape.

`local-store`:

- JSON load/save helpers.
- Debounced save and explicit flush.
- Cross-platform locking via `proper-lockfile`.
- Atomic write with Windows replacement fallback.

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
3. Implement JSON store primitives with locking and atomic writes.
4. Implement embedding provider adapter and similarity helpers.
5. Add package-level tests and cross-package contract tests.

## Key Contracts

- Stdout-facing result shapes follow `docs/cli-contract.md`.
- Config follows `docs/config.md`.
- Data layout follows `docs/data-layout.md`.
- Error codes are documented in `docs/error-codes.md`.
- Runtime is Node.js `>=20` with npm; Bun and Deno are not supported in Phase 1.
- Logger fields are fixed as `ts`, `level`, `msg`, `pkg`, `event`, `traceId?`, `details?`.
- Public APIs are exported only through each package `src/index.ts`.

## Acceptance Criteria

- Every helper is usable without Bridge runtime.
- JSON store writes are atomic.
- Lock timeout returns a stable error.
- Embedding tests can pass without real provider keys.
- Public exports are small and documented.
- Provider disabled state is distinct from provider unavailable state.

## Risks

- Over-abstracting before feature packages exist.
- Accidentally importing feature-specific behavior into shared packages.
- Logging sensitive content from provider payloads.
