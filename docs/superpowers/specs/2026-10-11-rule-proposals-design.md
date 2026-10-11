# Rule Proposals — Design

Date: 2026-10-11
Status: Approved (implemented)

References: `docs/superpowers/specs/2026-09-21-mail-organizer-design.md` (product spec,
rule detection described in the scan flow and in the apply step),
`docs/superpowers/specs/2026-09-22-api-frontend-design.md` (API this builds on), ADRs
0003, 0008, 0012, 0013.

## Goal

Fourth and last planned subsystem. After a scan, when several emails from the same
sender (or domain) were proposed for the same destination folder, propose a server-side
rule — "emails from X → move to folder Y" — so future emails are filed automatically.
The rule is only ever created after explicit user approval, like every other action
(ADR-0012).

Out of scope: IMAP accounts (`supports_rules()` is false), rules that delete, applying
a rule retroactively to existing mail, listing or editing rules that already exist on
the server, tuning the threshold from the UI.

## Decisions taken during brainstorming

| Question | Decision |
|---|---|
| Sender and domain both reach the threshold for the same folder | Propose only the most specific (sender) rule; a domain rule is considered only for emails not already covered by a sender rule. |
| Avoiding duplicate rules on later scans (providers cannot list rules) | Remember rules this app created in a new `applied_rules` table and do not propose a rule for the same account and condition again. Rules created by hand in the webmail are not visible. |
| Gmail rule semantics | The Gmail filter must label **and** remove `INBOX`, so it behaves like "move" (same as `move_message` and as the Graph rule). |
| Where rule proposals live | Same `proposals` table, new action `create_rule`; the existing approve/reject/batch endpoints, lock, retry and UI are reused. |
| Existing `app.db` after the schema change | Automatic additive migration (`ALTER TABLE ADD COLUMN`), no data loss. |

## Behaviour

### Detection (pure function, `mail_organizer/rules.py`)

`detect_rule_candidates(proposals, existing_rules, threshold) -> list[RuleCandidate]`

- Input: the job's proposals (dicts as returned by `Database.list_proposals`), the
  account's existing applied rules `{(kind, value)}`, and the threshold (default 3).
- Only proposals with `action == "move"`, a non-empty `target_folder` and a valid sender
  are considered. `flag_delete`, `keep`, `error` and existing `create_rule` proposals
  never count.
- Step 1, senders: group by `(sender, target_folder)`. A sender produces a candidate when
  its best folder has `count >= threshold` **and** strictly more emails than any other
  folder for that sender; otherwise that sender produces nothing.
- Step 2, domains: emails whose sender produced a candidate in step 1 are removed. The
  rest are grouped by `(domain, target_folder)` with the same threshold and strict
  majority rule.
- A candidate is dropped if `(kind, value)` is already in `existing_rules`, whatever the
  folder (two rules for one condition would conflict).
- A candidate value must match a strict pattern before it can become a proposal: sender
  `^[^\s@<>"',;()\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`, domain
  `^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`. The sender comes from an email header and ends up in
  a provider query, so anything else is skipped silently.
- Output is deterministic: sorted by count descending, then kind, then value.
- `RuleCandidate(kind: str, value: str, folder: str, count: int)`.

### Scan integration (`scan.py`)

- `run_scan(..., rule_threshold: int = 3)`.
- After the message loop and before marking the job `completed`: if
  `provider.supports_rules()`, read `db.list_proposals(job_id)` and
  `db.list_applied_rules(account_id)`, run detection and store each candidate with
  `db.add_proposal(job_id, "", "create_rule", folder, reason, rule_kind=..., rule_value=...,
  rule_match_count=...)`.
- `reason` is a generated Portuguese sentence, e.g. "3 emails deste lote vão para
  Promotions" (UI strings stay Portuguese, as in the rest of the product).
- Any exception in this block is swallowed (the job still ends `completed`, without rule
  proposals). It must never turn a finished scan into a failed one.
- The account id comes from `db.get_job(job_id)["account_id"]`.
- Threshold comes from `RULE_MIN_EMAILS` (integer ≥ 1, default 3) read in `main.py`,
  passed through `create_app(..., rule_min_emails=...)` into `start_scan`.

### Storage (`db.py`)

- `proposals` gains nullable `rule_kind TEXT`, `rule_value TEXT`, `rule_match_count
  INTEGER`; `list_proposals` and `get_proposal` return them.
- `message_id` is `""` for rule proposals (column stays `NOT NULL`). `sender` holds the
  rule value so the UI shows who the rule is about; `subject`, `date`, `snippet` stay null.
- New table `applied_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
  kind TEXT NOT NULL, value TEXT NOT NULL, folder TEXT NOT NULL, provider_rule_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account_id, kind, value))`
  with a foreign key to `accounts`.
- `add_applied_rule(account_id, kind, value, folder, provider_rule_id)` (idempotent on
  the unique key) and `list_applied_rules(account_id) -> list[dict]`.
- `init_schema` becomes additive-migrating: after `CREATE TABLE IF NOT EXISTS`, every
  expected column missing from `proposals`/`jobs` is added with `ALTER TABLE ... ADD
  COLUMN` (all expected columns are nullable or have a default). `SchemaOutOfDateError`
  remains only for a case that cannot be migrated (for example an expected column
  that cannot be added). ADR-0003 is updated: "no migration framework; additive column
  migrations only".

### Applying a rule (`apply.py`, `routes_proposals.py`)

- `apply_proposal` gains a `create_rule` branch: refuse if `not provider.supports_rules()`;
  resolve `target_folder` name → `Folder.id` through `list_folders()` (same as `move`);
  build `RuleCondition(sender=...)` or `RuleCondition(domain=...)` from `rule_kind` /
  `rule_value`; call `provider.create_rule(condition, folder_id)`.
- `ApplyResult` gains `rule_id: str | None = None`.
- The approve routes need no new endpoint. On a successful `create_rule` result they
  also call `db.add_applied_rule(...)`, inside the same approval lock and before the
  proposal is marked `applied`, using `job["account_id"]`.
- `NotImplementedError` and any `ProviderError`/`OSError` become a failure result (the
  proposal stays `pending` with `applied_error`, retryable). Everything else already
  covered by the generic backstop.
- Rule proposals reuse the existing provider-opening helper unchanged (selecting the
  job's folder is a no-op for Gmail and Graph, the only providers that support rules).
  They have no message, so the "Ver conteúdo" button is not rendered for them and the
  content endpoint is never called with an empty `message_id`.

### Gmail filter (`providers/gmail.py`)

`create_rule` body becomes `action: {addLabelIds: [target_folder], removeLabelIds:
["INBOX"]}`. Test updated accordingly.

### Frontend (`static/app.js`)

- Proposals are grouped by action under headings: "Mover", "Possível lixo/phishing",
  "Regras sugeridas", "Manter", "Erro" (this also delivers the grouping the product spec
  asks for).
- A rule proposal renders "Criar regra: emails de `<value>` → mover para `<folder>`"
  plus "N emails neste lote", built with `textContent` only (ADR-0006), with the usual
  approve/reject controls and batch checkbox. No content preview.

## Error handling summary

| Failure | Result |
|---|---|
| Detection raises | Scan still `completed`; no rule proposals. |
| `supports_rules()` false (IMAP) | No rule proposals are generated; a stray rule proposal cannot be applied (failure result). |
| Target folder renamed or deleted before approval | Failure result naming the folder; proposal stays `pending`. |
| Provider rejects the rule or the network fails | Failure result; retryable; emails already applied are untouched. |
| Rule already applied | `409`, as for any applied proposal; `applied_rules` unique key prevents a second row. |

## Testing

- `tests/test_rules.py`: threshold boundaries (2 vs 3), strict majority and tie, sender
  beats domain, domain built only from uncovered emails, existing rule suppression
  (any folder), invalid sender skipped, only `move` counts, deterministic order,
  configurable threshold.
- `tests/test_apply.py`: `create_rule` success (returns `rule_id`), unsupported provider,
  folder missing, `ProviderError`, `NotImplementedError`, sender vs domain condition.
- `tests/test_scan.py`: rule proposals stored for a supporting provider, not for IMAP,
  detection failure does not fail the job, real-`Database` integration with a threshold.
- `tests/test_db.py`: new columns round-trip, `applied_rules` add/list/uniqueness,
  additive migration from the previous and from the pre-API schemas.
- `tests/api/test_routes_proposals.py`: approving a rule proposal creates the rule and an
  `applied_rules` row, re-approve gives 409, failure then retry works, batch containing
  email and rule proposals, rule failure does not affect email proposals.
- `tests/providers/test_gmail.py`: filter labels and removes `INBOX`.
- Frontend: manual checklist only (as in the API spec); `node --check` and a grep for
  `innerHTML` stay mandatory.

## Open risks (accepted)

- Rules created by hand on the server are invisible, so a duplicate can still be
  proposed for them (mitigated only for rules created by this app).
- Graph `senderContains` is a substring match: a sender rule for `a@b.com` also matches
  `aa@b.com`, and a domain rule `@b.com` also matches `x@b.com.evil.tld`. Gmail's
  `from:` filter does not have this looseness for full addresses. Accepted for a
  user-approved, local, single-user MVP; the proposal text shows the exact condition.
- Rule creation shares the global approval lock with email approvals, so approvals are
  serialized (as today).
