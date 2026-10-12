# Rule Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a scan, propose server-side rules ("emails from X -> move to folder Y") for Gmail and Graph accounts when several emails from the same sender or domain were proposed for the same folder; create the rule only after explicit approval.

**Architecture:** A pure detection function (`rules.py`) runs at the end of `run_scan` and stores each candidate as a `create_rule` proposal in the existing `proposals` table, so the approve/reject/batch endpoints, lock, retry and UI are reused. `apply_proposal` gains a `create_rule` branch; on success the approve route records the rule in a new `applied_rules` table so later scans do not propose it again. `init_schema` becomes additively migrating so existing databases keep their data.

**Tech Stack:** Python 3.12+, FastAPI, SQLite, pytest, vanilla JS (existing; no new dependencies).

**Spec:** `docs/superpowers/specs/2026-10-11-rule-proposals-design.md` (and the product spec `docs/superpowers/specs/2026-09-21-mail-organizer-design.md`).

## Global Constraints

- **Nothing executes without approval (ADR-0012):** a rule is created only inside `approve`/`batch-approve`, never during a scan.
- **Rules only move to a folder, never delete.** No rule action may remove a message or trash it.
- **IMAP is out of scope:** `supports_rules()` is false there; no rule proposal may be generated for it and a stray one must fail to apply with a clear message.
- **A rule proposal needs no message:** `message_id` is `""`; the "Ver conteudo" button and the content endpoint are never used for it.
- **Only `move` proposals with a valid sender count toward a rule.** `flag_delete`, `keep`, `error` and existing `create_rule` proposals never count.
- **Sender beats domain:** a domain rule is considered only for emails not already covered by a sender rule; ties and non-majority folders produce no rule.
- **Duplicate suppression:** a candidate whose `(kind, value)` already exists in `applied_rules` for the account is dropped, whatever the folder.
- **The rule value comes from an email header and ends up in a provider filter:** it must match the strict patterns in `rules.py` or it is skipped.
- **Folder name -> id is resolved at apply time** with a fresh `provider.list_folders()` (as for `move`).
- **An applied proposal is permanent** (409 on re-approve); a failed apply stays `pending` with `applied_error` and is retryable. A bookkeeping failure after the provider created the rule must not leave the proposal retryable (a retry would create a duplicate rule).
- **Detection failure never fails a scan:** the job still ends `completed`.
- **Existing databases keep their data:** schema changes are additive `ALTER TABLE ... ADD COLUMN` only (ADR-0003: still no migration framework).
- **Dynamic text in the UI is rendered with `textContent` only (ADR-0006)**; no `innerHTML` anywhere in `app.js`.
- **Tests never touch the network or a real provider (ADR-0011).**
- **User-facing strings stay Portuguese; code, docs and ADRs are English.**
- **Commit messages end with:** `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`

## Review Focus

- **A sender whose emails split across folders with no strict majority (tie):** no rule is proposed (never an arbitrary pick). Test in Task 1.
- **A sender string with characters unsafe for a provider filter** (spaces, quotes, parentheses, `OR`-style injection): skipped, never proposed. Test in Task 1.
- **Approving a rule whose target folder was renamed or deleted since the scan:** clear failure, proposal stays `pending`, no `applied_rules` row, nothing created. Tests in Tasks 4 and 6.
- **The provider creates the rule but recording it locally fails (or the user double-clicks):** the proposal ends `applied`, exactly one rule is created, a second approve is 409. Test in Task 6.
- **An existing `app.db` from before this change:** `init_schema` migrates it in place and old proposals/jobs/accounts are still readable; an IMAP account scan produces no rule proposals. Tests in Tasks 2 and 5.

---

### Task 1: Pure rule detection

**Files:**
- Create: `mail_organizer/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) RuleCandidate(kind: str, value: str, folder: str, count: int)` where `kind` is `"sender"` or `"domain"`.
  - `detect_rule_candidates(proposals: list[dict], existing_rules: list[tuple[str, str]], threshold: int = 3) -> list[RuleCandidate]`.
  - `proposals` are dicts as returned by `Database.list_proposals` (keys used: `action`, `target_folder`, `sender`); `existing_rules` is a list of `(kind, value)`.
- Consumes: nothing (no I/O, no imports from the rest of the package).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rules.py
from mail_organizer.rules import RuleCandidate, detect_rule_candidates


def _move(sender, folder="Promotions", **extra):
    proposal = {"action": "move", "target_folder": folder, "sender": sender}
    proposal.update(extra)
    return proposal


def test_three_emails_from_one_sender_to_one_folder_propose_a_sender_rule():
    proposals = [_move("news@shop.com")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3)]


def test_below_threshold_proposes_nothing():
    proposals = [_move("news@shop.com")] * 2

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_threshold_is_configurable():
    proposals = [_move("news@shop.com")] * 2

    result = detect_rule_candidates(proposals, [], threshold=2)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 2)]


def test_sender_is_normalized_to_lowercase():
    proposals = [_move("News@Shop.COM")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3)]


def test_tie_between_two_folders_proposes_nothing():
    proposals = [_move("a@shop.com", "Promotions")] * 3 + [_move("a@shop.com", "Updates")] * 3

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_strict_majority_folder_wins_even_with_another_folder_present():
    proposals = [_move("a@shop.com", "Promotions")] * 4 + [_move("a@shop.com", "Updates")] * 1

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 4)]


def test_domain_rule_when_no_single_sender_reaches_threshold_but_the_domain_does():
    proposals = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("domain", "shop.com", "Promotions", 3)]


def test_sender_rule_wins_and_domain_only_counts_uncovered_emails():
    # a@ has 3 (sender rule); the 2 others from the domain are below threshold on their own.
    proposals = [_move("a@shop.com")] * 3 + [_move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 3)]


def test_domain_rule_is_built_from_emails_not_covered_by_a_sender_rule():
    proposals = (
        [_move("a@shop.com")] * 3
        + [_move("b@shop.com"), _move("c@shop.com"), _move("d@shop.com")]
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [
        RuleCandidate("domain", "shop.com", "Promotions", 3),
        RuleCandidate("sender", "a@shop.com", "Promotions", 3),
    ]


def test_only_move_proposals_count():
    proposals = (
        [{"action": "flag_delete", "target_folder": None, "sender": "a@shop.com"}] * 5
        + [{"action": "keep", "target_folder": None, "sender": "a@shop.com"}] * 5
        + [{"action": "create_rule", "target_folder": "Promotions", "sender": "a@shop.com"}] * 5
    )

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_existing_rule_for_same_condition_suppresses_candidate_for_any_folder():
    proposals = [_move("a@shop.com", "Promotions")] * 3

    result = detect_rule_candidates(proposals, [("sender", "a@shop.com")], threshold=3)

    assert result == []


def test_emails_of_a_sender_with_an_existing_rule_do_not_feed_a_domain_rule():
    proposals = [_move("a@shop.com")] * 3 + [_move("b@shop.com")] * 2

    result = detect_rule_candidates(proposals, [("sender", "a@shop.com")], threshold=3)

    assert result == []


def test_existing_domain_rule_suppresses_domain_candidate():
    proposals = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [("domain", "shop.com")], threshold=3)

    assert result == []


def test_unsafe_or_malformed_senders_are_skipped():
    bad = [
        "a b@shop.com",
        'a"@shop.com',
        "a(b)@shop.com",
        "no-at-sign",
        "a@localhost",
        "",
        None,
    ]
    proposals = [_move(sender) for sender in bad for _ in range(5)]

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_proposals_without_target_folder_are_ignored():
    proposals = [{"action": "move", "target_folder": None, "sender": "a@shop.com"}] * 5

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_output_is_ordered_by_count_then_kind_then_value():
    proposals = (
        [_move("z@one.com")] * 3
        + [_move("a@two.com")] * 5
        + [_move("b@two.com")] * 3
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert [(c.value, c.count) for c in result] == [("a@two.com", 5), ("b@two.com", 3), ("z@one.com", 3)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.rules'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/rules.py
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

# The sender comes from an email header and ends up in a provider filter, so
# anything that is not a plain address is skipped instead of escaped.
SENDER_RE = re.compile(r"^[^\s@<>\"',;()\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class RuleCandidate:
    kind: str  # "sender" | "domain"
    value: str
    folder: str
    count: int


def _dominant_folder(folders: Counter, threshold: int) -> tuple[str, int] | None:
    ranked = folders.most_common()
    folder, count = ranked[0]
    if count < threshold:
        return None
    if len(ranked) > 1 and ranked[1][1] == count:
        return None
    return folder, count


def detect_rule_candidates(
    proposals: list[dict],
    existing_rules: list[tuple[str, str]],
    threshold: int = 3,
) -> list[RuleCandidate]:
    existing = {(kind, value.lower()) for kind, value in existing_rules}

    by_sender: dict[str, Counter] = defaultdict(Counter)
    for proposal in proposals:
        if proposal.get("action") != "move" or not proposal.get("target_folder"):
            continue
        sender = (proposal.get("sender") or "").strip().lower()
        if not SENDER_RE.match(sender):
            continue
        by_sender[sender][proposal["target_folder"]] += 1

    candidates: list[RuleCandidate] = []
    covered: set[str] = set()
    for sender, folders in by_sender.items():
        dominant = _dominant_folder(folders, threshold)
        if dominant is None:
            continue
        # Covered even when an existing rule suppresses the candidate: those
        # emails are already handled and must not feed a broader domain rule.
        covered.add(sender)
        if ("sender", sender) in existing:
            continue
        candidates.append(RuleCandidate("sender", sender, dominant[0], dominant[1]))

    by_domain: dict[str, Counter] = defaultdict(Counter)
    for sender, folders in by_sender.items():
        if sender in covered:
            continue
        domain = sender.split("@", 1)[1]
        if not DOMAIN_RE.match(domain):
            continue
        by_domain[domain].update(folders)

    for domain, folders in by_domain.items():
        dominant = _dominant_folder(folders, threshold)
        if dominant is None or ("domain", domain) in existing:
            continue
        candidates.append(RuleCandidate("domain", domain, dominant[0], dominant[1]))

    candidates.sort(key=lambda c: (-c.count, c.kind, c.value))
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rules.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/rules.py tests/test_rules.py
git commit -m "feat: add pure rule-candidate detection"
```

---

### Task 2: Persistence — rule columns, applied_rules table, additive migration

**Files:**
- Modify: `mail_organizer/db.py`
- Test: `tests/test_db.py`, `tests/test_scan.py` (exact-dict assertion)

**Interfaces:**
- Consumes: existing `Database`.
- Produces:
  - `proposals` gains nullable `rule_kind TEXT`, `rule_value TEXT`, `rule_match_count INTEGER`; `list_proposals`/`get_proposal` return those three keys.
  - `Database.add_proposal(job_id, message_id, action, target_folder, reason, sender=None, subject=None, date=None, snippet=None, rule_kind=None, rule_value=None, rule_match_count=None)`.
  - `Database.add_applied_rule(account_id: str, kind: str, value: str, folder: str, provider_rule_id: str | None = None) -> None` (idempotent on `(account_id, kind, value)`).
  - `Database.list_applied_rules(account_id: str) -> list[dict]` with keys `kind`, `value`, `folder`, `provider_rule_id`, ordered by insertion.
  - `init_schema()` migrates additively; `SchemaOutOfDateError` is raised only if an `ALTER TABLE` fails.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, update the three exact-dict assertions that list every proposal key. In `test_add_and_list_proposals_roundtrip_in_insertion_order` both dicts, and in `test_get_proposal_returns_full_row_including_job_id`, add these three keys to each dict:

```python
"rule_kind": None, "rule_value": None, "rule_match_count": None,
```

In `tests/test_scan.py::test_run_scan_integrates_with_a_real_database`, add the same three keys to the `proposals[0]` dict.

Replace `test_init_schema_raises_for_a_database_created_before_the_new_columns` in `tests/test_db.py` with these tests (keep `test_init_schema_accepts_a_fresh_database`):

```python
def _old_shape_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE accounts (account_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            display_name TEXT NOT NULL, credentials_encrypted BLOB NOT NULL);
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, total INTEGER NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'running', error_message TEXT);
        CREATE TABLE proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            message_id TEXT NOT NULL, action TEXT NOT NULL, target_folder TEXT, reason TEXT NOT NULL);
        INSERT INTO accounts VALUES ('acc-1', 'imap', 'old', X'00');
        INSERT INTO jobs (job_id, account_id, total) VALUES ('job-1', 'acc-1', 1);
        INSERT INTO proposals (job_id, message_id, action, target_folder, reason)
            VALUES ('job-1', 'msg-1', 'move', 'Promotions', 'old row');
        """
    )
    conn.commit()
    conn.close()


def test_init_schema_migrates_an_old_database_in_place_keeping_its_rows(tmp_path):
    path = tmp_path / "old.db"
    _old_shape_database(path)
    key = load_or_create_key(tmp_path / "secret.key")

    with Database(path, key) as old:
        old.init_schema()

        proposal = old.get_proposal(1)
        assert proposal["message_id"] == "msg-1"
        assert proposal["applied_status"] == "pending"
        assert proposal["sender"] is None
        assert proposal["rule_kind"] is None
        assert old.get_job("job-1")["folder"] is None
        assert old.list_applied_rules("acc-1") == []


def test_init_schema_migration_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    _old_shape_database(path)
    key = load_or_create_key(tmp_path / "secret.key")

    with Database(path, key) as old:
        old.init_schema()
        old.init_schema()


def test_init_schema_raises_schema_out_of_date_when_an_alter_fails(tmp_path):
    from mail_organizer.db import SchemaOutOfDateError

    path = tmp_path / "old.db"
    _old_shape_database(path)
    key = load_or_create_key(tmp_path / "secret.key")

    class _FailingAlter:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            if sql.lstrip().upper().startswith("ALTER TABLE"):
                raise sqlite3.OperationalError("boom")
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    with Database(path, key) as old:
        old._conn = _FailingAlter(old._conn)
        with pytest.raises(SchemaOutOfDateError) as excinfo:
            old.init_schema()

    assert "old.db" in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)


def test_rule_proposal_fields_round_trip(db):
    db.save_account("acc-1", "gmail", "x", {"refresh_token": "t"})
    db.create_job("job-1", "acc-1", total=0)

    db.add_proposal(
        "job-1", "", "create_rule", "Promotions", "3 emails",
        sender="news@shop.com", rule_kind="sender", rule_value="news@shop.com", rule_match_count=3,
    )

    proposal = db.list_proposals("job-1")[0]
    assert proposal["action"] == "create_rule"
    assert proposal["message_id"] == ""
    assert proposal["rule_kind"] == "sender"
    assert proposal["rule_value"] == "news@shop.com"
    assert proposal["rule_match_count"] == 3
    assert db.get_proposal(proposal["id"])["rule_value"] == "news@shop.com"


def test_applied_rules_add_and_list_in_insertion_order(db):
    db.save_account("acc-1", "gmail", "x", {"refresh_token": "t"})

    db.add_applied_rule("acc-1", "sender", "a@shop.com", "Promotions", "rule-1")
    db.add_applied_rule("acc-1", "domain", "other.com", "Updates", None)

    assert db.list_applied_rules("acc-1") == [
        {"kind": "sender", "value": "a@shop.com", "folder": "Promotions", "provider_rule_id": "rule-1"},
        {"kind": "domain", "value": "other.com", "folder": "Updates", "provider_rule_id": None},
    ]


def test_applied_rules_are_scoped_to_the_account(db):
    db.save_account("acc-1", "gmail", "x", {"refresh_token": "t"})
    db.save_account("acc-2", "gmail", "y", {"refresh_token": "t"})

    db.add_applied_rule("acc-1", "sender", "a@shop.com", "Promotions", "rule-1")

    assert db.list_applied_rules("acc-2") == []


def test_add_applied_rule_is_idempotent_on_account_kind_value(db):
    db.save_account("acc-1", "gmail", "x", {"refresh_token": "t"})

    db.add_applied_rule("acc-1", "sender", "a@shop.com", "Promotions", "rule-1")
    db.add_applied_rule("acc-1", "sender", "a@shop.com", "Updates", "rule-2")

    rules = db.list_applied_rules("acc-1")
    assert len(rules) == 1
    assert rules[0]["folder"] == "Promotions"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py tests/test_scan.py -v`
Expected: FAIL — exact-dict assertions miss the new keys, `add_applied_rule`/`list_applied_rules` do not exist, `add_proposal` rejects `rule_kind`.

- [ ] **Step 3: Implement**

In `mail_organizer/db.py`:

Add three columns to the `proposals` table in `SCHEMA` (after `applied_error TEXT,`):

```sql
    rule_kind TEXT,
    rule_value TEXT,
    rule_match_count INTEGER,
```

Append to `SCHEMA` (after the `proposals` table):

```sql
CREATE TABLE IF NOT EXISTS applied_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    folder TEXT NOT NULL,
    provider_rule_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, kind, value),
    FOREIGN KEY (account_id) REFERENCES accounts (account_id)
);
```

Replace `EXPECTED_COLUMNS` with:

```python
# Columns added after the first schema version. CREATE TABLE IF NOT EXISTS leaves
# existing tables untouched, so init_schema adds whatever is missing (additive
# only; there is no migration framework, ADR-0003).
ADDED_COLUMNS = {
    "jobs": {
        "error_message": "TEXT",
        "folder": "TEXT",
    },
    "proposals": {
        "sender": "TEXT",
        "subject": "TEXT",
        "date": "TEXT",
        "snippet": "TEXT",
        "applied_status": "TEXT NOT NULL DEFAULT 'pending'",
        "applied_error": "TEXT",
        "rule_kind": "TEXT",
        "rule_value": "TEXT",
        "rule_match_count": "INTEGER",
    },
}
```

Replace the column-check loop in `init_schema` with:

```python
        for table, columns in ADDED_COLUMNS.items():
            actual = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns.items():
                if name in actual:
                    continue
                try:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                except sqlite3.OperationalError as exc:
                    raise SchemaOutOfDateError(
                        f"O banco de dados '{self._path}' é de uma versão anterior e não pôde ser "
                        f"atualizado (tabela '{table}', coluna '{name}'). "
                        "Apague o arquivo ou mova-o para outro lugar e inicie de novo."
                    ) from exc
```

Update the docstring of `SchemaOutOfDateError` to: `"""The database file is from an older schema version and could not be migrated."""`.

Replace `add_proposal`, `list_proposals`, `get_proposal` and add the two new methods:

```python
    def add_proposal(
        self,
        job_id: str,
        message_id: str,
        action: str,
        target_folder: str | None,
        reason: str,
        sender: str | None = None,
        subject: str | None = None,
        date: str | None = None,
        snippet: str | None = None,
        rule_kind: str | None = None,
        rule_value: str | None = None,
        rule_match_count: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO proposals
                    (job_id, message_id, action, target_folder, reason, sender, subject, date, snippet,
                     rule_kind, rule_value, rule_match_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, message_id, action, target_folder, reason, sender, subject, date, snippet,
                 rule_kind, rule_value, rule_match_count),
            )
            self._conn.commit()

    def list_proposals(self, job_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, message_id, action, target_folder, reason, applied_status, applied_error,
                   sender, subject, date, snippet, rule_kind, rule_value, rule_match_count
            FROM proposals WHERE job_id = ? ORDER BY id
            """,
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_proposal(self, proposal_id: int) -> dict | None:
        row = self._conn.execute(
            """
            SELECT id, job_id, message_id, action, target_folder, reason, applied_status, applied_error,
                   sender, subject, date, snippet, rule_kind, rule_value, rule_match_count
            FROM proposals WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()
        return dict(row) if row else None

    def add_applied_rule(
        self,
        account_id: str,
        kind: str,
        value: str,
        folder: str,
        provider_rule_id: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO applied_rules (account_id, kind, value, folder, provider_rule_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, kind, value, folder, provider_rule_id),
            )
            self._conn.commit()

    def list_applied_rules(self, account_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT kind, value, folder, provider_rule_id
            FROM applied_rules WHERE account_id = ? ORDER BY id
            """,
            (account_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py tests/test_scan.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all green (exact-dict assertions elsewhere must already include the new keys; fix any other test that pins the proposal shape the same way, never weakening it).

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/db.py tests/test_db.py tests/test_scan.py
git commit -m "feat: add rule fields, applied_rules table and additive schema migration"
```

---

### Task 3: Gmail filter must label and archive

**Files:**
- Modify: `mail_organizer/providers/gmail.py`
- Test: `tests/providers/test_gmail.py`

**Interfaces:**
- Consumes/Produces: `GmailProvider.create_rule(condition, target_folder) -> str` unchanged signature; the filter action becomes `{"addLabelIds": [target_folder], "removeLabelIds": ["INBOX"]}`.

- [ ] **Step 1: Update the failing tests**

In `tests/providers/test_gmail.py`, in both `test_create_rule_with_sender_condition_calls_filters_create` and `test_create_rule_with_domain_condition_uses_wildcard`, change the expected `"action"` value from

```python
"action": {"addLabelIds": ["Promotions"]},
```

to

```python
"action": {"addLabelIds": ["Promotions"], "removeLabelIds": ["INBOX"]},
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/providers/test_gmail.py -k create_rule -v`
Expected: FAIL (the call body lacks `removeLabelIds`)

- [ ] **Step 3: Implement**

In `GmailProvider.create_rule`, replace the `body` with:

```python
        body = {
            "criteria": {"from": sender_pattern},
            "action": {"addLabelIds": [target_folder], "removeLabelIds": ["INBOX"]},
        }
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/providers/test_gmail.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/providers/gmail.py tests/providers/test_gmail.py
git commit -m "feat: make Gmail rules label and archive so they behave like a move"
```

---

### Task 4: Apply a create_rule proposal

**Files:**
- Modify: `mail_organizer/apply.py`
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: `RuleCondition(sender=..., domain=...)` and `EmailProvider.supports_rules()/create_rule()/list_folders()` (existing).
- Produces: `ApplyResult(success: bool, message: str, rule_id: str | None = None)`; `apply_proposal` handles `action == "create_rule"` using proposal keys `rule_kind`, `rule_value`, `target_folder`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_apply.py`:

```python
def _rule_proposal(**overrides) -> dict:
    fields = dict(
        action="create_rule", message_id="", target_folder="Promotions",
        rule_kind="sender", rule_value="news@shop.com", rule_match_count=3,
    )
    fields.update(overrides)
    return _proposal(**fields)


def _rule_provider(folders=None, rule_id="rule-1"):
    provider = MagicMock()
    provider.supports_rules.return_value = True
    provider.list_folders.return_value = folders or [Folder(id="Label_7", name="Promotions")]
    provider.create_rule.return_value = rule_id
    return provider


def test_create_rule_with_sender_condition_resolves_folder_and_returns_rule_id():
    provider = _rule_provider()

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is True
    assert result.rule_id == "rule-1"
    condition, folder_id = provider.create_rule.call_args.args
    assert condition.sender == "news@shop.com"
    assert condition.domain is None
    assert folder_id == "Label_7"
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def test_create_rule_with_domain_condition():
    provider = _rule_provider()

    result = apply_proposal(
        provider, _rule_proposal(rule_kind="domain", rule_value="shop.com")
    )

    assert result.success is True
    condition = provider.create_rule.call_args.args[0]
    assert condition.domain == "shop.com"
    assert condition.sender is None


def test_create_rule_fails_when_provider_does_not_support_rules():
    provider = _rule_provider()
    provider.supports_rules.return_value = False

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "suporta" in result.message
    provider.create_rule.assert_not_called()


def test_create_rule_fails_clearly_when_folder_no_longer_exists():
    provider = _rule_provider(folders=[Folder(id="INBOX", name="INBOX")])

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "Promotions" in result.message
    provider.create_rule.assert_not_called()


def test_create_rule_fails_when_list_folders_raises_provider_error():
    provider = _rule_provider()
    provider.list_folders.side_effect = ProviderError("auth expired")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "auth expired" in result.message


def test_create_rule_fails_when_provider_raises_provider_error():
    provider = _rule_provider()
    provider.create_rule.side_effect = ProviderError("quota exceeded")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "quota exceeded" in result.message


def test_create_rule_fails_when_provider_raises_not_implemented():
    provider = _rule_provider()
    provider.create_rule.side_effect = NotImplementedError("no rules")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False


def test_create_rule_fails_on_incomplete_proposal():
    provider = _rule_provider()

    result = apply_proposal(provider, _rule_proposal(rule_value=None))

    assert result.success is False
    provider.create_rule.assert_not_called()
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_apply.py -v -k create_rule`
Expected: FAIL (`create_rule` is treated as an unknown action; `ApplyResult` has no `rule_id`)

- [ ] **Step 3: Implement**

In `mail_organizer/apply.py`:

Change the imports and `ApplyResult`:

```python
from dataclasses import dataclass

from mail_organizer.providers.base import EmailProvider, RuleCondition
from mail_organizer.providers.errors import ProviderError


@dataclass
class ApplyResult:
    success: bool
    message: str
    rule_id: str | None = None
```

Add this helper above `apply_proposal`:

```python
def _apply_rule(provider: EmailProvider, proposal: dict) -> ApplyResult:
    if not provider.supports_rules():
        return ApplyResult(success=False, message="Este provedor não suporta a criação de regras")

    kind = proposal.get("rule_kind")
    value = proposal.get("rule_value")
    target_name = proposal.get("target_folder")
    if kind not in ("sender", "domain") or not value or not target_name:
        return ApplyResult(success=False, message="Proposta de regra incompleta")

    try:
        folders = provider.list_folders()
    except ProviderError as exc:
        return ApplyResult(success=False, message=f"Falha ao listar pastas: {exc}")

    matching = [f for f in folders if f.name == target_name]
    if not matching:
        return ApplyResult(success=False, message=f"Pasta '{target_name}' não existe mais na caixa")

    condition = RuleCondition(sender=value) if kind == "sender" else RuleCondition(domain=value)
    try:
        rule_id = provider.create_rule(condition, matching[0].id)
    except NotImplementedError:
        return ApplyResult(success=False, message="Este provedor não suporta a criação de regras")
    except ProviderError as exc:
        return ApplyResult(success=False, message=f"Falha ao criar a regra: {exc}")
    return ApplyResult(success=True, message=f"Regra criada: {value} → {target_name}", rule_id=rule_id)
```

In `apply_proposal`, add before the `keep`/`error` branch:

```python
    if action == "create_rule":
        return _apply_rule(provider, proposal)

```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_apply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/apply.py tests/test_apply.py
git commit -m "feat: apply create_rule proposals through the provider"
```

---

### Task 5: Generate rule proposals at the end of a scan

**Files:**
- Modify: `mail_organizer/scan.py`, `mail_organizer/api/routes_scan.py`, `mail_organizer/api/app.py`, `mail_organizer/api/main.py`
- Test: `tests/test_scan.py`, `tests/api/test_routes_scan.py`, `tests/api/test_main.py`

**Interfaces:**
- Consumes: `detect_rule_candidates`, `RuleCandidate` (Task 1); `Database.add_proposal(..., rule_kind, rule_value, rule_match_count)`, `list_applied_rules`, `list_proposals`, `get_job` (Task 2).
- Produces:
  - `run_scan(db, provider, llm_client, job_id, messages, rule_threshold: int = 3) -> None`.
  - `create_app(..., rule_min_emails: int = 3)` storing `app.state.rule_min_emails`.
  - `main.py` reads `RULE_MIN_EMAILS` (integer >= 1, default 3; invalid or < 1 falls back to 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan.py`:

```python
def _real_db(tmp_path):
    from mail_organizer.crypto import load_or_create_key
    from mail_organizer.db import Database

    key = load_or_create_key(tmp_path / "secret.key")
    db = Database(tmp_path / "test.db", key)
    db.init_schema()
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc"})
    return db


def _promo_llm():
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(
        folder="Promotions", suspicious=False, reason="Newsletter"
    )
    return llm_client


def _rules_provider(supports=True):
    provider = MagicMock()
    provider.supports_rules.return_value = supports
    provider.list_folders.return_value = [Folder(id="Promotions", name="Promotions")]
    return provider


def test_scan_proposes_a_sender_rule_when_threshold_is_reached(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    rules = [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["message_id"] == ""
    assert rule["target_folder"] == "Promotions"
    assert rule["rule_kind"] == "sender"
    assert rule["rule_value"] == "news@shop.com"
    assert rule["rule_match_count"] == 3
    assert rule["sender"] == "news@shop.com"
    assert "3" in rule["reason"] and "Promotions" in rule["reason"]
    assert db.get_job("job-1")["status"] == "completed"
    db.close()


def test_scan_does_not_propose_rules_below_threshold(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=2)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(2)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []
    db.close()


def test_scan_does_not_propose_rules_when_provider_does_not_support_them(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(supports=False), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []
    assert db.get_job("job-1")["status"] == "completed"
    db.close()


def test_scan_skips_a_rule_that_was_already_applied_for_the_account(tmp_path):
    db = _real_db(tmp_path)
    db.add_applied_rule("acc-1", "sender", "news@shop.com", "Promotions", "rule-1")
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []
    db.close()


def test_rule_detection_failure_does_not_fail_the_scan(tmp_path, monkeypatch):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    def boom(*args, **kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("mail_organizer.scan.detect_rule_candidates", boom)

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    job = db.get_job("job-1")
    assert job["status"] == "completed"
    assert len(db.list_proposals("job-1")) == 3
    db.close()
```

Append to `tests/api/test_routes_scan.py`:

```python
def test_start_scan_passes_the_configured_rule_threshold(db, monkeypatch):
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from mail_organizer.api.app import CSRF_HEADER, CSRF_HEADER_VALUE, create_app
    from mail_organizer.providers.base import EmailProvider, Folder

    class _Provider(EmailProvider):
        def __init__(self, credentials):
            pass

        def list_folders(self):
            return [Folder(id="INBOX", name="INBOX")]

        def list_messages(self, folder, filters):
            return []

        def get_message(self, message_id):
            raise NotImplementedError

        def move_message(self, message_id, target_folder):
            pass

        def delete_message(self, message_id):
            pass

    spy = MagicMock()
    monkeypatch.setattr("mail_organizer.api.routes_scan.run_scan", spy)
    db.save_account("acc-1", "fake", "x", {})
    app = create_app(db, {"fake": _Provider}, rule_min_emails=7)
    client = TestClient(app, headers={CSRF_HEADER: CSRF_HEADER_VALUE})

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert response.status_code == 201
    assert spy.call_args.kwargs["rule_threshold"] == 7
```

Append to `tests/api/test_main.py`:

```python
def _import_main(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    for name in ("APP_BASE_URL", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                 "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "RULE_MIN_EMAILS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    sys.modules.pop("mail_organizer.api.main", None)
    return importlib.import_module("mail_organizer.api.main")


@pytest.mark.parametrize(
    "raw,expected", [(None, 3), ("5", 5), ("1", 1), ("0", 3), ("-2", 3), ("abc", 3)]
)
def test_main_reads_rule_min_emails_with_a_safe_default(tmp_path, monkeypatch, raw, expected):
    env = {} if raw is None else {"RULE_MIN_EMAILS": raw}
    module = _import_main(tmp_path, monkeypatch, **env)
    try:
        assert module.app.state.rule_min_emails == expected
    finally:
        module.db.close()
        sys.modules.pop("mail_organizer.api.main", None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_scan.py tests/api/test_routes_scan.py tests/api/test_main.py -v`
Expected: FAIL (`run_scan` has no `rule_threshold`, `create_app` has no `rule_min_emails`, no rule proposals are generated)

- [ ] **Step 3: Implement**

`mail_organizer/scan.py` — add the import and helper, extend the signature, and call the helper before the final `completed` update:

```python
from mail_organizer.rules import detect_rule_candidates
```

```python
def _propose_rules(db: Database, provider: EmailProvider, job_id: str, threshold: int) -> None:
    if not provider.supports_rules():
        return
    account_id = db.get_job(job_id)["account_id"]
    existing = [(rule["kind"], rule["value"]) for rule in db.list_applied_rules(account_id)]
    for candidate in detect_rule_candidates(db.list_proposals(job_id), existing, threshold):
        db.add_proposal(
            job_id, "", "create_rule", candidate.folder,
            f"{candidate.count} emails deste lote vão para {candidate.folder}",
            sender=candidate.value, rule_kind=candidate.kind,
            rule_value=candidate.value, rule_match_count=candidate.count,
        )
```

Signature: add `rule_threshold: int = 3,` as the last parameter of `run_scan`. Replace the final `db.update_job_progress(job_id, processed, "completed")` with:

```python
        try:
            _propose_rules(db, provider, job_id, rule_threshold)
        except Exception:
            # Rule proposals are an extra: a failure here must never turn a
            # finished scan into a failed one.
            pass

        db.update_job_progress(job_id, processed, "completed")
```

`mail_organizer/api/app.py` — add `rule_min_emails: int = 3,` to the keyword parameters of `create_app` and `app.state.rule_min_emails = rule_min_emails` next to the other `app.state` assignments.

`mail_organizer/api/routes_scan.py` — replace the `background_tasks.add_task(...)` line with:

```python
    background_tasks.add_task(
        run_scan, db, provider, llm_client, job_id, messages,
        rule_threshold=request.app.state.rule_min_emails,
    )
```

`mail_organizer/api/main.py` — add above `app = create_app(...)`:

```python
def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value >= 1 else default


RULE_MIN_EMAILS = _positive_int_env("RULE_MIN_EMAILS", 3)
```

and pass `rule_min_emails=RULE_MIN_EMAILS,` to `create_app(...)`.

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_scan.py tests/api/test_routes_scan.py tests/api/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/scan.py mail_organizer/api/app.py mail_organizer/api/routes_scan.py mail_organizer/api/main.py tests/test_scan.py tests/api/test_routes_scan.py tests/api/test_main.py
git commit -m "feat: propose rules at the end of a scan with a configurable threshold"
```

---

### Task 6: Approving a rule records it

**Files:**
- Modify: `mail_organizer/api/routes_proposals.py`
- Test: `tests/api/test_routes_proposals.py`

**Interfaces:**
- Consumes: `ApplyResult.rule_id` (Task 4); `Database.add_applied_rule` (Task 2).
- Produces: after a successful `create_rule` apply, one `applied_rules` row `(account_id, rule_kind, rule_value, target_folder, rule_id)` exists and the proposal is `applied`. No new endpoints.

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_routes_proposals.py`, add these providers after `_FailingMoveProvider`:

```python
class _RuleProvider(_FakeProvider):
    created = []

    def supports_rules(self):
        return True

    def create_rule(self, condition, target_folder):
        _RuleProvider.created.append((condition.sender, condition.domain, target_folder))
        return "rule-1"
```

Extend the `provider_factories` fixture's returned dict with `"rule": _RuleProvider`, and add to the autouse `_reset_selected_folders` fixture a line `_RuleProvider.created.clear()` (before or after `SELECTED_FOLDERS.clear()`).

Add the seed helper and tests:

```python
def _seed_rule_proposal(db, provider_type="rule", folder_name="Promotions", rule_kind="sender", rule_value="news@shop.com"):
    db.save_account("acc-1", provider_type, "x", {})
    db.create_job("job-1", "acc-1", total=0)
    db.add_proposal(
        "job-1", "", "create_rule", folder_name, "3 emails deste lote vão para Promotions",
        sender=rule_value, rule_kind=rule_kind, rule_value=rule_value, rule_match_count=3,
    )
    return db.list_proposals("job-1")[0]["id"]


def test_approve_rule_creates_it_and_records_it(client, db):
    proposal_id = _seed_rule_proposal(db)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert _RuleProvider.created == [("news@shop.com", None, "Label_7")]
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"
    assert db.list_applied_rules("acc-1") == [
        {"kind": "sender", "value": "news@shop.com", "folder": "Promotions", "provider_rule_id": "rule-1"}
    ]


def test_approve_domain_rule_uses_a_domain_condition(client, db):
    proposal_id = _seed_rule_proposal(db, rule_kind="domain", rule_value="shop.com")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert _RuleProvider.created == [(None, "shop.com", "Label_7")]


def test_approving_a_rule_twice_creates_it_once(client, db):
    proposal_id = _seed_rule_proposal(db)
    client.post(f"/proposals/{proposal_id}/approve")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 409
    assert len(_RuleProvider.created) == 1


def test_approve_rule_fails_when_target_folder_no_longer_exists(client, db):
    proposal_id = _seed_rule_proposal(db, folder_name="Ghost Folder")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    assert "Ghost Folder" in response.json()["detail"]
    proposal = db.get_proposal(proposal_id)
    assert proposal["applied_status"] == "pending"
    assert proposal["applied_error"]
    assert db.list_applied_rules("acc-1") == []
    assert _RuleProvider.created == []


def test_approve_rule_fails_for_a_provider_without_rule_support(client, db):
    proposal_id = _seed_rule_proposal(db, provider_type="fake")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    assert db.get_proposal(proposal_id)["applied_status"] == "pending"
    assert db.list_applied_rules("acc-1") == []


def test_rule_stays_applied_when_recording_it_locally_fails(client, db, monkeypatch):
    proposal_id = _seed_rule_proposal(db)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "add_applied_rule", boom)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"
    assert client.post(f"/proposals/{proposal_id}/approve").status_code == 409
    assert len(_RuleProvider.created) == 1


def test_batch_approve_applies_email_and_rule_proposals_independently(client, db):
    db.save_account("acc-1", "rule", "x", {})
    db.create_job("job-1", "acc-1", total=1)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "r1")
    db.add_proposal(
        "job-1", "", "create_rule", ("Ghost Folder"), "r2",
        sender="news@shop.com", rule_kind="sender", rule_value="news@shop.com", rule_match_count=3,
    )
    ids = [p["id"] for p in db.list_proposals("job-1")]

    response = client.post("/proposals/batch-approve", json={"ids": ids})

    results = response.json()
    assert results[str(ids[0])] == "ok"
    assert results[str(ids[1])].startswith("error:")
    assert db.get_proposal(ids[0])["applied_status"] == "applied"
    assert db.get_proposal(ids[1])["applied_status"] == "pending"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/api/test_routes_proposals.py -v -k "rule"`
Expected: FAIL (`applied_rules` stays empty after approve)

- [ ] **Step 3: Implement**

In `routes_proposals.py::_apply_and_record`, replace the final block (the `db.mark_proposal_applied(...)` and `return`) with:

```python
    if result.success and proposal["action"] == "create_rule":
        try:
            db.add_applied_rule(
                job["account_id"], proposal["rule_kind"], proposal["rule_value"],
                proposal["target_folder"], result.rule_id,
            )
        except Exception:
            # The rule already exists on the server. A bookkeeping failure must
            # not leave the proposal retryable: a retry would create a duplicate.
            pass

    db.mark_proposal_applied(
        proposal["id"],
        "applied" if result.success else "pending",
        None if result.success else result.message,
    )
    return {"success": result.success, "message": result.message}
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/api/test_routes_proposals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/api/routes_proposals.py tests/api/test_routes_proposals.py
git commit -m "feat: record applied rules when a rule proposal is approved"
```

---

### Task 7: Frontend — grouped proposals and rule rendering

**Files:**
- Modify: `mail_organizer/static/app.js`, `mail_organizer/static/style.css`
- No automated tests (frontend is covered by the manual checklist, ADR-0006/0011); verification is `node --check`, a grep, and a TestClient static check.

**Interfaces:**
- Consumes: proposal dicts from `GET /jobs/{id}/proposals` including `rule_kind`, `rule_value`, `rule_match_count`, `target_folder`.
- Produces: proposals grouped under a heading per action, in the order `move`, `create_rule`, `flag_delete`, `keep`, `error`; rule proposals show "Criar regra: emails de X → mover para Y" and the match count, and have no "Ver conteúdo" button.

- [ ] **Step 1: Implement**

In `mail_organizer/static/app.js`, replace the `ACTION_LABELS` block with:

```javascript
const ACTION_LABELS = {
  move: "Mover",
  create_rule: "Regras sugeridas",
  flag_delete: "Possível lixo/phishing",
  keep: "Manter",
  error: "Erro",
};
const GROUP_ORDER = ["move", "create_rule", "flag_delete", "keep", "error"];
```

In `buildProposal`, replace the block from `div.appendChild(makeEl("strong", ...ACTION_LABELS...` through the `if (proposal.snippet) ...` line with:

```javascript
  const isRule = proposal.action === "create_rule";
  if (isRule) {
    const kindLabel = proposal.rule_kind === "domain" ? "do domínio" : "de";
    div.appendChild(
      makeEl("strong", {
        text: `Criar regra: emails ${kindLabel} ${proposal.rule_value || ""} → mover para ${proposal.target_folder || ""}`,
      })
    );
    if (proposal.rule_match_count) {
      div.appendChild(
        makeEl("div", { className: "preview", text: `${proposal.rule_match_count} emails neste lote` })
      );
    }
  } else {
    div.appendChild(makeEl("strong", { text: ACTION_LABELS[proposal.action] || String(proposal.action) }));
    if (proposal.target_folder) {
      div.appendChild(makeEl("span", { text: ` → ${proposal.target_folder}` }));
    }
    // Plain-text preview of the message; older rows may lack these fields.
    for (const [label, value] of [
      ["De:", proposal.sender],
      ["Assunto:", proposal.subject],
      ["Data:", proposal.date],
    ]) {
      if (value) div.appendChild(makeEl("div", { className: "preview", text: `${label} ${value}` }));
    }
    if (proposal.snippet) div.appendChild(makeEl("div", { className: "snippet", text: proposal.snippet }));
  }
```

Replace these two lines (they create the "Ver conteúdo" button):

```javascript
  const view = makeEl("button", { className: "view-content", text: "Ver conteúdo" });
  view.addEventListener("click", () => toggleContent(proposal, holder, errorEl, view));
```

with:

```javascript
  // Rule proposals have no message, so there is nothing to preview.
  const view = isRule ? null : makeEl("button", { className: "view-content", text: "Ver conteúdo" });
  if (view) view.addEventListener("click", () => toggleContent(proposal, holder, errorEl, view));
```

and replace the final line of `buildProposal`, `  div.append(approve, reject, view, errorEl, holder);`, with:

```javascript
  if (view) {
    div.append(approve, reject, view, errorEl, holder);
  } else {
    div.append(approve, reject, errorEl);
  }
```

(Leave the `function lockActions()` declaration between those two edits exactly where it is.)

In `loadProposals`, replace the `for (const proposal of proposals) { ... }` loop with:

```javascript
    const groups = GROUP_ORDER.map((action) => [
      ACTION_LABELS[action],
      proposals.filter((proposal) => proposal.action === action),
    ]);
    // An action this UI does not know yet must still be visible, never silently dropped.
    const unknown = proposals.filter((proposal) => !GROUP_ORDER.includes(proposal.action));
    if (unknown.length > 0) groups.push(["Outras", unknown]);

    for (const [title, group] of groups) {
      if (group.length === 0) continue;
      container.appendChild(makeEl("h3", { className: "group-title", text: `${title} (${group.length})` }));
      for (const proposal of group) {
        const node = buildProposal(proposal);
        if (keepError && keepError.id === proposal.id) {
          node.querySelector(".proposal-error").textContent = keepError.message;
        }
        container.appendChild(node);
      }
    }
```

In `mail_organizer/static/style.css`, append:

```css
.group-title { margin-top: 1.25rem; }
```

- [ ] **Step 2: Verify**

Run:
```bash
node --check mail_organizer/static/app.js
grep -n innerHTML mail_organizer/static/app.js
python - <<'PY'
from fastapi.testclient import TestClient
from mail_organizer.api.app import create_app
from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database
import pathlib, tempfile
d = pathlib.Path(tempfile.mkdtemp())
db = Database(d / "a.db", load_or_create_key(d / "k"))
db.init_schema()
c = TestClient(create_app(db, {}, static_dir="mail_organizer/static"))
for path in ("/", "/app.js", "/style.css"):
    assert c.get(path).status_code == 200, path
assert "create_rule" in c.get("/app.js").text
print("static ok")
db.close()
PY
```
Expected: `node --check` prints nothing, the `grep` prints nothing (no `innerHTML` use), and the script prints `static ok`.

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: all green

- [ ] **Step 4: Commit**

```bash
git add mail_organizer/static/app.js mail_organizer/static/style.css
git commit -m "feat: group proposals by action and render rule proposals in the UI"
```

---

### Task 8: Docs and full verification

**Files:**
- Modify: `docs/adr/0003-sqlite-local-database.md`, `README.md`, `docs/superpowers/specs/2026-10-11-rule-proposals-design.md`

- [ ] **Step 1: Update ADR-0003**

In `docs/adr/0003-sqlite-local-database.md`, under "Consequences", replace the two bullets about migrations and `SchemaOutOfDateError` with:

```markdown
- **No migration framework:** `CREATE TABLE IF NOT EXISTS` does not alter existing tables, so `init_schema` additively adds the columns that are missing (`ALTER TABLE ... ADD COLUMN`, always nullable or with a default) and creates new tables. Existing data is kept. A change that cannot be expressed as an additive column (renaming, dropping, changing a type) still needs a new ADR.
- `init_schema` raises `SchemaOutOfDateError` only if an additive `ALTER TABLE` fails (delete or move the file aside in that case).
```

- [ ] **Step 2: Update README and spec status**

In `README.md`, replace

```
4. 🔄 API + frontend plan → Ready for implementation (subagent-driven)
5. ⏳ Rules proposal plan (future)
```

with

```
4. ✅ API + frontend plan → Implemented
5. ✅ Rule proposals plan → Implemented (`docs/superpowers/plans/2026-10-11-rule-proposals.md`)
```

In the spec, change `Status: Awaiting review (written 2026-10-11)` to `Status: Approved (implemented)`.

- [ ] **Step 3: Full verification**

Run:
```bash
pytest -q
grep -l "import requests\|import sqlite3\|from mail_organizer.db" mail_organizer/rules.py mail_organizer/heuristics.py mail_organizer/proposals.py
node --check mail_organizer/static/app.js
```
Expected: all tests pass (previous 258 plus the new ones, 1 skipped); the `grep` prints nothing (the pure modules stay pure); `node --check` prints nothing.

- [ ] **Step 4: Manual smoke (not in CI)**

Run a real server against a throwaway data dir (the migration itself is covered by the Task 2 tests):
```bash
MAIL_ORGANIZER_DATA_DIR="$(mktemp -d)" python -m uvicorn mail_organizer.api.main:app --port 8124 &
sleep 3; curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8124/accounts; kill %1
```
Expected: `200`.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0003-sqlite-local-database.md README.md docs/superpowers/specs/2026-10-11-rule-proposals-design.md
git commit -m "docs: record additive migrations and mark rule proposals implemented"
```
