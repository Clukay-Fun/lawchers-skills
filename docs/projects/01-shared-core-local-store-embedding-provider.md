# Project 1: Shared Core / Local Store / Embedding Provider

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
- Lightweight logger.
- Trace IDs and observability event shape.

`local-store`:

- JSON load/save helpers.
- Debounced save and explicit flush.
- Lock file behavior.
- Atomic rename.
- Temp workspace naming helpers if shared by later packages.

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

## Acceptance Criteria

- Every helper is usable without Bridge runtime.
- JSON store writes are atomic.
- Lock timeout returns a stable error.
- Embedding tests can pass without real provider keys.
- Public exports are small and documented.

## Risks

- Over-abstracting before feature packages exist.
- Accidentally importing feature-specific behavior into shared packages.
- Logging sensitive content from provider payloads.
