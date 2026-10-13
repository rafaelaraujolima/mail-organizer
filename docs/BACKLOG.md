# Backlog

Open follow-ups, known risks and unvalidated areas. Each item names where it came from.
Priority: **P1** = do before trusting the app with a real mailbox, **P2** = soon,
**P3** = polish or accepted risk. When an item is resolved, delete it here and note it in
[STATUS.md](STATUS.md) or the PR.

## P1 — validation and correctness risks

| Item | Source | Notes |
|---|---|---|
| Manual checklist ([MANUAL-TESTING.md](MANUAL-TESTING.md)) never run for the frontend (connect, scan, preview, approve/reject, batch, rules group) | PR #4, PR #5 | UI verified only by `node --check`, grep for `innerHTML` and `TestClient` static checks |
| Gmail filters and Graph message rules never created against the real APIs | PR #5 review | All provider tests use mocks (ADR-0011). Gmail needs `gmail.settings.basic`; accounts connected earlier must reconnect |
| Gmail domain rule uses `from: *@domain`; wildcard syntax unconfirmed | PR #5 review | Fails safe (matches nothing) but may not work; `@domain` is the documented form |
| `mark_proposal_applied` is unguarded right after a successful `create_rule` | PR #5 review | Only a disk/I-O failure triggers it; the "rule already exists" pre-check prevents a duplicate on retry, but the proposal stays `pending` |
| `_apply_and_record` raises `TypeError` if the proposal's job is missing | PR #4 re-review | Pre-existing; foreign key makes it very unlikely |

## P2 — product gaps

| Item | Source | Notes |
|---|---|---|
| No per-group "select all" (product spec: approve in batch per group) | PR #5 review | Grouping is delivered; the checkbox selection is per item |
| OAuth callbacks return raw JSON in the browser tab instead of redirecting to the UI | PR #4 | Also: OAuth accounts get a fixed display name ("Gmail"/"Outlook"); connect buttons are shown even when the provider is not configured (503 JSON) |
| A rule proposal is not blocked or outvoted by the same sender's `flag_delete`/`keep` proposals | PR #5 review (Ruling 8) | The reason text shows "N de M emails"; semantics follow the spec literally |
| Rejected proposals cannot be re-approved from the UI (the API allows it) | PR #4 review | |
| Checkbox selection is lost when the proposal list reloads; duplicate poll chains if a scan is restarted mid-poll; "Ver conteúdo" double-click guard only | PR #4 review | |
| IMAP opens a new connection and login per proposal in a batch | PR #4 review | May be throttled by iCloud on large batches; cache the provider per batch |
| Graph refresh token rotates and the new one is not persisted | PR #4 review | Graph accounts need reconnecting after ~90 days of inactivity (ADR-0009) |
| `POST /scan` runs `list_messages` inside the request | PR #4 review | For IMAP this fetches every full message synchronously; large folders give very long requests |

## P2 — connector limitations (pre-existing, outside the API/rules work)

| Item | Source |
|---|---|
| Graph `list_folders` has no pagination and no child folders; folders can be missing from the dropdown and from what the LLM sees | PR #4 final review |
| Gmail `list_folders` offers system labels (UNREAD, SENT, TRASH...) as move targets; the rules side is guarded, the per-email `move` path is not | PR #4 / PR #5 reviews |
| Gmail `move_message` strips the message's other user labels | PR #4 final review |
| Gmail `list_messages` returns only the first page | PR #4 final review |
| Graph rules use `sequence: 1` and `stopProcessingRules: true`, which pre-empts the user's own Outlook rules | PR #5 review |
| Graph `senderContains` is a substring match (`a@shop.com` also matches `ba@shop.com`) | PR #5 spec (accepted risk) |
| System-folder denylist for rules is name-based; localized Outlook names (e.g. "Itens Excluídos") are not recognised | PR #5 review |

## P3 — hygiene and accepted risks

| Item | Source |
|---|---|
| Spec text for rule proposals is stale (regexes, `RuleCandidate.total`, failure table) | PR #5 re-review |
| Only Python 3.14 tested; 3.12/3.13 untested; no CI matrix (ADR-0002) | ADR-0002 |
| `StarletteDeprecationWarning` about `httpx` in the test client | PR #4 |
| `oauth_states` is an in-memory set that is never pruned | PR #4 |
| Reads on the shared SQLite connection do not take the write lock (measured safe under serialized mode) | PR #4 final review |
| `reject` does not take the approval lock; end state is still correct | PR #4 final review |
| Sanitizer: an unquoted `href` loses its visible URL (output stays inert); an unclosed `<script>` leaves escaped text | PR #4 Task 1 review |
| IMAPClient is not closed after a failed login (socket released on garbage collection) | PR #4 Task 3 review |
| ADR-0003 "Considered alternatives" still says "3 simple tables" | PR #5 Task 8 review |
| Swallow-all blocks log only a warning with ids; no structured logging elsewhere | PR #5 review |

## Not planned (explicit non-goals)

Learning from past decisions, multi-tenant or hosted deployment, permanent deletion, rules
that delete, IMAP rules (no standard server-side filter API), applying a rule retroactively.
See the product spec for the full list.
