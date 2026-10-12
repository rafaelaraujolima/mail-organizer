# Mail Organizer — instructions for Claude Code

Local, single-user email organizer: scans a mailbox (Gmail, Outlook/Graph, IMAP), uses
heuristics plus a local LLM (Ollama) to **propose** moves, deletions (to Trash) and
server-side rules, and applies them only after explicit user approval.

## Start here (every new context window)

1. Read [docs/STATUS.md](docs/STATUS.md): what is done, what is next, how to resume.
2. Read [docs/BACKLOG.md](docs/BACKLOG.md): open follow-ups, known risks, unvalidated areas.
3. Skim [docs/adr/README.md](docs/adr/README.md): binding technology decisions.
4. Before designing anything, read the relevant spec in `docs/superpowers/specs/` and plan in
   `docs/superpowers/plans/`. The specs are the binding authority; plans argue from them.

Rationale for past judgment calls is in
[docs/decisions/development-rulings.md](docs/decisions/development-rulings.md). Do not
re-litigate a recorded ruling without new information.

## Conventions

- **Language:** code, docs, ADRs, README and commit messages are English. User-facing UI
  strings and runtime messages shown to the user are Portuguese (pt-BR), as in the existing code.
- **Safety invariant (ADR-0012):** nothing is executed against a mailbox without explicit
  approval. Delete always means move to the provider's Trash. Never add an automatic path.
- **Untrusted content:** email bodies, senders and LLM output are untrusted. The frontend
  uses `textContent` only (ADR-0006); HTML goes through `sanitize_html` (ADR-0010).
- **Tests:** `python -m pytest -q` (currently 372 passed, 1 skipped). No test may touch the
  network, a real mail provider or Ollama (ADR-0011). Negative tests need a positive control.
- **Workflow:** brainstorm -> written spec -> written plan -> subagent-driven execution in a
  git worktree (`.claude/worktrees/<name>`), per-task review, whole-branch review, PR.
  Technology decisions get an ADR (ADR-0001).
- **Git:** `main` is protected and PRs are squash-merged, so a local `main` that carried
  unpushed commits will diverge. Branch from `origin/main`; never commit to `main` directly.
- **GitHub CLI on this machine:** the active `gh` account can be an Enterprise Managed User
  that cannot create PRs on this personal repo. Use the repo owner's token for that one
  command: `GH_TOKEN="$(gh auth token --user rafaelaraujolima)" gh pr create ...`.
- **Scratch:** `.superpowers/` (subagent ledgers, briefs, reports) and `.claude/worktrees/`
  are local and git-ignored. Anything that must survive a session goes into `docs/`.

## Keeping the project state current (do this at the end of every phase)

- Update `docs/STATUS.md` (phase table, next step, test count, last-updated date).
- Move resolved items out of `docs/BACKLOG.md` and add new ones with their source.
- Append the controller rulings made during the phase to
  `docs/decisions/development-rulings.md` (decision, why, cost if wrong).
- New spec -> `docs/superpowers/specs/`, new plan -> `docs/superpowers/plans/`, new
  technology decision -> `docs/adr/` (and its index).

## Running it

```bash
pip install -e ".[dev]"
python -m pytest -q
MAIL_ORGANIZER_DATA_DIR=/tmp/mo uvicorn mail_organizer.api.main:app --port 8000
```

Environment variables are listed in [README.md](README.md#configuration).
