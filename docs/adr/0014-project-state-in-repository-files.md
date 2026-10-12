# ADR-0014: Project State Is Kept in Repository Files

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Development is done across many short-lived sessions and context windows. The state of the
project (what is done, what is next, why a judgment call was made) lived only in
conversation history and in git-ignored scratch (`.superpowers/`), which is deleted at the
end of each plan. A new session could not tell where work stopped.

## Decision

Everything a new session needs to resume is committed to the repository:

- `CLAUDE.md` at the root, loaded automatically by Claude Code, points to the files below
  and states the project conventions.
- `docs/STATUS.md`: phase table, where things are, safety invariants, next steps, how to resume.
- `docs/BACKLOG.md`: open follow-ups and known risks with priority and source.
- `docs/decisions/development-rulings.md`: judgment calls made while executing plans.
- `docs/adr/`: technology and architecture decisions (ADR-0001). `docs/superpowers/specs/`
  and `plans/`: what to build and how.

At the end of every phase these files are updated in the same PR (or an immediate follow-up
docs PR) as the code. Scratch under `.superpowers/` and `.claude/worktrees/` stays ignored.

## Considered Alternatives

- **Rely on conversation memory or per-user auto-memory:** not shared across machines or
  people, not reviewable, and silently lost on a context reset.
- **One long changelog:** mixes state, risks and rationale; hard to scan on resume.

## Consequences

- A phase is not finished until STATUS, BACKLOG and the rulings log are current.
- These documents can go stale; `STATUS.md` carries a "last updated" date and the `main`
  commit it describes so staleness is visible.
