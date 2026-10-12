# Development Rulings

Judgment calls made by the controller during subagent-driven development, where a plan
was ambiguous, wrong or in conflict with the spec. Each entry records **what was
decided**, **why** and **what it costs if wrong**, so a later session does not
re-litigate it without new information. Technology decisions live in `docs/adr/`; this
file is for process and scope decisions. Newest phase last.

Entries marked *(reconstructed)* were recovered from a session summary rather than the
original ledger. The connectors phase (PR #1) predates this log and has no entries.

## Phase 2 — Scan engine (PR #2) *(reconstructed)*

Whole-branch review produced five Important findings; four were fixed in one wave.

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| 2.1 | `run_scan` got an outer `try/except` backstop so no unanticipated exception can leave a job stuck in `running` | The spec requires that a job is never left hanging; the plan's code only caught two named exceptions | A broad catch can hide a bug behind a failed job message |
| 2.2 | The link heuristic no longer flags the sender's own subdomains (`www.paypal.com`) as lookalikes | Plan code defeated the heuristic's own purpose and would flag ordinary marketing mail | A real lookalike on a sender subdomain is not flagged |
| 2.3 | Folder names suggested by the LLM are validated against the real folder list and dropped if absent | Small models hallucinate folders; Gmail pseudo-labels also pollute the list | A valid folder with an unexpected name loses its suggestion |
| 2.4 | Storing the folder **name** (not the provider id) in proposals was kept; resolution to id happens at apply time | Folders can change between scan and approval; the apply phase re-resolves anyway | Needs a fresh `list_folders()` call per apply |
| 2.5 | Any single heuristic flag or LLM suspicion escalates to `flag_delete` (OR combination) was kept | Plan-mandated; every proposal is human-reviewed, so a false positive costs one rejection, not data | More noise in review; tuning deferred |
| 2.6 | An integration test against a real SQLite `Database` was added for the scan/persistence boundary | Only mocks covered it; FK and ordering regressions would be invisible | None |

## Phase 4 — API + frontend (PR #4)

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| 4.1 | The frontend must not use `innerHTML` for anything derived from email, LLM or provider; build nodes with `textContent` | ADR-0006; LLM text over attacker-controlled mail is stored XSS in the review UI | A more verbose `app.js` |
| 4.2 | `reject` returns 409 when the proposal is already applied | An executed move/delete cannot be "rejected"; the plan overwrote the status and hid that it ran | One extra branch and test |
| 4.3 | OAuth `state` was first left unvalidated (localhost MVP); **superseded by 4.9** | | |
| 4.4 | Model tiers: haiku for tasks whose code is fully in the plan, sonnet for judgment/multi-file tasks, most capable model for the final review | Cost and turn count | An extra fix round |
| 4.5 | `connect_imap` catches `(ProviderError, OSError)` -> 400 and never saves unverified credentials | A mistyped host would otherwise be a 500 | One `except` clause and a test |
| 4.6 | Inserted **Task 5b**: `EmailProvider.select_folder(folder)` hook and `jobs.folder` | IMAP ids are per-folder UIDs and the provider is rebuilt per request, so approve/preview would fail for every IMAP account | Two additive edits to already-merged modules |
| 4.7 | Failures to open a provider (auth refresh, connect, no factory) are per-item results, not crashes; later widened to every route | Review Focus: a failing item must not abort a batch or become a 500 | Slightly larger routes |
| 4.8 | Frontend shows content only in a sandboxed `<iframe sandbox srcdoc>`, handles every async error inline, no `alert()` | Defense in depth over bleach; the plan left promise rejections unhandled | Slightly larger `app.js` |
| 4.9 | Final fix wave (one dispatch): permanence + concurrency lock, all unhandled-500 paths, CSRF/DNS-rebinding hardening (ADR-0013), OAuth `state` validated and single-use, proposal preview fields (sender/subject/date/snippet), additive DB detection, regression tests | Verified by execution by the final reviewer: concurrent approve executed twice; a cross-site POST applied a proposal | Wave larger than a pure bug fix; every POST test needs the header |
| 4.10 | Not in the wave: browser checklist, grouping by action, OAuth callback redirect, per-batch IMAP login, connector issues | Pre-existing or product-level; see BACKLOG | User follow-ups |

Controller slips worth remembering: the final-review prompt for Task 7 told the reviewer not
to report the missing OAuth `state` (pre-judging, forbidden); and the ADR-0013 text was first
written in Portuguese against the standing English-docs rule.

## Phase 5 — Rule proposals (PR #5)

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| 5.1 | Sender beats domain: a domain rule is built only from emails not covered by a sender rule | Spec behaviour; avoids overlapping rules | Fewer domain rules |
| 5.2 | Rules already created by this app are remembered in `applied_rules`; no provider `list_rules` | The connector interface cannot list rules; adding it touches reviewed code and OAuth scopes | Rules created by hand in the webmail are invisible |
| 5.3 | Gmail filters label **and** remove `INBOX` | Behave like a move, as Graph and `move_message` do | Users who wanted label-only filters |
| 5.4 | Rule proposals live in the `proposals` table with action `create_rule`; additive `ALTER TABLE` migration | Reuses the approval lock, retry, UI; avoids deleting users' databases on every schema change | `message_id` is `""` for rules |
| 5.5 | Dominance is **plurality with a strict lead** (A=3,B=2,C=2 proposes A), not >50% | What the spec's behaviour section literally says | An extra proposal the user can reject |
| 5.6 | Plan-mandated tests that passed with no implementation were strengthened; negative tests carry a positive control | A test that cannot fail protects nothing | A few extra test lines |
| 5.7 | Final fix wave: `gmail.settings.basic` scope, "rule already exists" pre-check before any provider call, system-folder denylist (detection and apply), strict sender/domain patterns, "N de M" reason, threshold clamp, logging, migration tests | Verified: Gmail filter creation needs the settings scope; repeated scans created duplicate/conflicting rules; three moves to TRASH produced a rule to TRASH | Gmail users re-consent once |
| 5.8 | Not in the wave: letting non-move proposals block a rule, per-group select-all, Gmail `*@domain` syntax, Graph substring matching | Spec literal / product decisions / pre-existing | Follow-ups, see BACKLOG |
| 5.9 | Stale spec text (regexes, `RuleCandidate.total`, failure table) parked | Not functional; the skill allows no second wave for final-review findings | Readers see old regexes |
