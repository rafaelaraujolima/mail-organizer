# ADR-0001: Recording Architecture Decisions in ADRs

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Technology decisions were scattered across specs and implementation plans without recording the rationale. This makes it hard to revisit decisions later or know if they were deliberate.

## Decision

Each relevant technology or architecture decision becomes an ADR in `docs/adr/NNNN-title.md`, in English, using short MADR format: Status, Date, Context, Decision, Alternatives Considered, Consequences. An accepted ADR is not edited to change the decision: a new one is created to replace it, and the old one moves to "Superseded by ADR-NNNN".

## Alternatives Considered

- **Keep decisions only in specs:** specs describe the product, not why; mixing them obscures both.

## Consequences

- Every spec or plan introducing a new technology references (or creates) the corresponding ADR.
- Index in [README.md](../../README.md).
