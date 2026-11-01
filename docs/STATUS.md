# Project Status

**Last updated:** 2026-10-12 · **`main` at:** `8ea0cfe` (PR #5) · **Tests:** 372 passed, 1 skipped

This file is the entry point for resuming work. Read it first, then
[BACKLOG.md](BACKLOG.md). Rationale for judgment calls: [decisions/development-rulings.md](decisions/development-rulings.md).

## One-paragraph summary

Mail Organizer is a local single-user app. It scans a mailbox (Gmail, Outlook/Graph, IMAP),
combines technical phishing heuristics with a local LLM (Ollama) to produce **proposals**
(move to a folder, flag as junk/phishing for deletion to Trash, or create a server-side
rule), and applies them only after explicit user approval. All four planned subsystems are
implemented and merged. What remains is validation against real accounts and the backlog.

## Phases

| # | Phase | Spec | Plan | PR / commit | State |
|---|---|---|---|---|---|
| 0 | Product design | [2026-09-21-mail-organizer-design](superpowers/specs/2026-09-21-mail-organizer-design.md) | — | `4892589`, `a8979a1` | Done |
| 1 | Connectors and persistence (Gmail, Graph, IMAP, SQLite, Fernet) | product spec | [connectors-and-persistence](superpowers/plans/2026-09-21-connectors-and-persistence.md) | #1 `ff1f700` | Done |
| 2 | Scan engine (heuristics, Ollama classification, proposals) | product spec | [scan-engine-heuristics-llm](superpowers/plans/2026-09-21-scan-engine-heuristics-llm.md) | #2 `ca56037` | Done |
| 3 | Documentation baseline (README, ADRs 0001–0012) | — | — | #3 `3c9735b` | Done |
| 4 | API + frontend (OAuth, scan jobs, review, approve/apply, hardening) | [api-frontend-design](superpowers/specs/2026-09-22-api-frontend-design.md) | [api-frontend](superpowers/plans/2026-09-22-api-frontend.md) | #4 `899387a` | Done (UI not browser-tested) |
| 5 | Rule proposals (detection, apply, applied-rules memory, grouped UI) | [rule-proposals-design](superpowers/specs/2026-10-11-rule-proposals-design.md) | [rule-proposals](superpowers/plans/2026-10-11-rule-proposals.md) | #5 `8ea0cfe` | Done (never run against real Gmail/Graph) |
| 6 | Project state in files (this documentation set) | — | — | `docs/project-state` | In review |

## Where things are

| Concern | Location |
|---|---|
| Provider interface and connectors | `mail_organizer/providers/` (`base.py`, `gmail.py`, `graph.py`, `imap.py`) |
| Provider factories (refresh-token -> access token) | `mail_organizer/factories.py`, `mail_organizer/oauth.py` |
| Persistence (SQLite, additive migration) | `mail_organizer/db.py` |
| Scan orchestration | `mail_organizer/scan.py` (+ `heuristics.py`, `llm.py`, `proposals.py`) |
| Rule detection (pure) | `mail_organizer/rules.py` |
| Applying approved proposals | `mail_organizer/apply.py` |
| HTML sanitization | `mail_organizer/sanitize.py` |
| HTTP API and wiring | `mail_organizer/api/` (`app.py`, `routes_*.py`, `main.py`) |
| Frontend (vanilla HTML/JS) | `mail_organizer/static/` |
| Tests | `tests/` (API tests in `tests/api/`, providers in `tests/providers/`) |
| Technology decisions | `docs/adr/` |

## Safety invariants (do not weaken)

- Nothing is executed against a mailbox without explicit approval (ADR-0012). The scan only
  writes proposals; `move`/`delete`/`create_rule` happen only in approve/batch-approve.
- An applied proposal is permanent (409 on re-approve); a failed apply stays `pending`
  with `applied_error` and is retryable; a rule is never created twice for the same
  account and condition.
- Mutating requests require `X-Requested-With: mail-organizer`; hosts are allow-listed;
  the OAuth `state` is single-use (ADR-0013).
- Untrusted text is rendered with `textContent` only; HTML goes through `sanitize_html`.

## Immediate next steps (in order)

1. **Run the manual checklist** in [MANUAL-TESTING.md](MANUAL-TESTING.md) (never done):
   IMAP connect, scan, preview, approve/reject, batch, double-click, failed approve then
   retry, grouped view. Record the outcome in its Results table.
2. **Validate against real providers** (sections 5-7 of the same checklist) with a throwaway
   mailbox: Gmail (reconnect to grant
   `gmail.settings.basic`, create a filter, confirm it labels and archives) and Graph
   (create a rule, confirm the condition and the target folder).
3. **Sync stale spec text:** `docs/superpowers/specs/2026-10-11-rule-proposals-design.md`
   still shows the pre-fix regexes, a 4-field `RuleCandidate` (no `total`) and lacks the
   "rule already exists" / "system target refused" rows in its failure table.
4. **Triage the backlog** ([BACKLOG.md](BACKLOG.md)); the items marked P1 should come first.
5. Decide the next phase with the user (candidates: per-group select-all and UI polish,
   OAuth callback redirect and account naming, provider pagination fixes, CI).

## How to resume work

1. `git fetch origin && git checkout -b <topic> origin/main` (never work on `main`).
2. `pip install -e ".[dev]"` and `python -m pytest -q` (expect 372 passed, 1 skipped).
3. For a new feature: brainstorm -> spec in `docs/superpowers/specs/` -> plan in
   `docs/superpowers/plans/` -> subagent-driven execution in `.claude/worktrees/<topic>`.
4. For a fix: write the failing test first; keep the safety invariants above.
5. At the end of the phase, update this file, [BACKLOG.md](BACKLOG.md) and
   [decisions/development-rulings.md](decisions/development-rulings.md).

## Environment notes

- Only Python 3.14 has been exercised; the floor is 3.12 (ADR-0002) and 3.12/3.13 are untested.
- pytest emits a known `StarletteDeprecationWarning` about `httpx` in `starlette.testclient`.
- There is no CI yet; tests run locally.
- An `app.db` created by an older version is migrated in place on startup (additive
  `ALTER TABLE` only, ADR-0003).
