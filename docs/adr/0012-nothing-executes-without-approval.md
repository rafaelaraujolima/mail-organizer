# ADR-0012: Nothing Executes Without Explicit User Approval

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The product reads and organizes emails with fallible heuristics and a small LLM. A wrong action (move or delete) on a real inbox is expensive for the user.

## Decision

The scan **only proposes**: it records proposals (`move`, `flag_delete`, `keep`, `error`) with short justification, never touching the inbox. Move or delete happens only in `approve`/`batch-approve`, by explicit user action, individual or in batch.

- `delete` always moves to the provider's Trash; never permanent deletion.
- A successfully applied proposal is never re-applied (`409`); a failure stays pending and can be retried.
- Failure on one email or one application does not cancel the batch; it is reported per item.
- The app does not store history of approval/rejection decisions.

## Considered Alternatives

- **Auto-apply above a confidence threshold:** the small LLM does not provide calibrated confidence; unacceptable risk.

## Consequences

- Heuristic false positives cost the user one rejected suggestion, not data loss.
- Server-side rules (Gmail/Graph) only move to folders, never delete.
