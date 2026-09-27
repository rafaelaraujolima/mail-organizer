# ADR-0011: Testing Strategy with pytest, Dependency Injection, No Network

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The product touches real email accounts and a local LLM. Tests cannot depend on real accounts, network, or Ollama running.

## Decision

- **pytest** framework; `httpx` as dev dependency for FastAPI `TestClient`.
- I/O modules receive their clients by **dependency injection** (HTTP session, Google service, IMAP client, provider factories) and tests use `unittest.mock`/fakes. No automated test accesses Google, Microsoft, IMAP, or external network.
- Pure logic (phishing heuristics, proposal generation, sanitization) tested in isolation, no I/O.
- Real Ollama test is optional, skipped (`skipif`) when unavailable; verifies response format only.
- Integration tests use real SQLite in `tmp_path`.
- Frontend: no automated tests; guided manual checklist.

## Considered Alternatives

- **Tests against real accounts in CI:** requires secrets, fragile.

## Consequences

- Good speed and determinism; residual risk of mock/real divergence, covered only by manual end-to-end testing.
