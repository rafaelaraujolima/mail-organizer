# Documentation Index

| Document | Purpose |
|---|---|
| [STATUS.md](STATUS.md) | **Start here.** Where the project is, what is next, how to resume |
| [BACKLOG.md](BACKLOG.md) | Open follow-ups, known risks, unvalidated areas, with priority and source |
| [decisions/development-rulings.md](decisions/development-rulings.md) | Process and scope judgment calls made during development, with rationale |
| [adr/README.md](adr/README.md) | Architecture Decision Records (technology and architecture choices) |
| [superpowers/specs/](superpowers/specs/) | Binding design specs, one per subsystem |
| [superpowers/plans/](superpowers/plans/) | Implementation plans that argue from the specs |

Related files at the repository root: [../README.md](../README.md) (product overview and
configuration) and [../CLAUDE.md](../CLAUDE.md) (instructions loaded automatically by
Claude Code in every new session).

## Where to record what

| You are recording... | Put it in |
|---|---|
| A technology or architecture decision | a new ADR in `adr/` (and update its index) |
| What a subsystem must do | a spec in `superpowers/specs/` |
| How to build it, task by task | a plan in `superpowers/plans/` |
| A judgment call made while executing a plan | `decisions/development-rulings.md` |
| Something left undone or a known risk | `BACKLOG.md` |
| Current state and next steps | `STATUS.md` |
