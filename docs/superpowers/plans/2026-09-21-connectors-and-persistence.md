# Conectores e Persistência — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `EmailProvider` interface, its three implementations (Gmail,
Graph/Outlook, IMAP), the encrypted-credential SQLite persistence layer, and an
account-connection service — the foundation every later subsystem (scan engine,
frontend, rules) is built on.

**Architecture:** A `mail_organizer` Python package with a provider layer
(`providers/`) implementing a common `EmailProvider` ABC behind dependency
injection (each provider takes an already-authenticated client/session object,
so tests mock that client and never hit real APIs), and a persistence layer
(`db.py`, `crypto.py`) storing encrypted OAuth tokens / IMAP credentials in
SQLite. This plan produces a library with full unit test coverage; it does not
wire up FastAPI routes or the OAuth browser redirect flow — those belong to the
next plan (scan engine + API), which will call `connect_account()` from this
plan's `AccountService`.

**Tech Stack:** Python 3.11+, `cryptography` (Fernet), `sqlite3` (stdlib),
`google-api-python-client` (Gmail), `requests` (Graph — no heavy SDK, matches
spec's "sem framework pesado" spirit), `imapclient` (IMAP), `pytest` +
`unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-21-mail-organizer-design.md`

## Global Constraints

- **Persistência SQLite local**, usada apenas para: estado dos jobs de scan,
  tokens OAuth / credenciais IMAP criptografados em repouso, config de conexão
  por conta. **Não** guarda histórico de decisões de aprovação/rejeição.
- **Criptografia:** `cryptography.Fernet`, chave gerada localmente no primeiro
  uso (nunca hardcoded, nunca logada).
- **Delete nunca é permanente** — `delete_message` sempre move para
  Trash/Lixeira do provedor.
- Cada provider é **isolado atrás da interface comum** `EmailProvider` —
  nenhum código fora de `providers/` deve importar `googleapiclient`,
  `requests` (para Graph), ou `imapclient` diretamente.
- `ImapProvider.supports_rules()` retorna `False`; `create_rule` não
  implementado para IMAP (fora de escopo, ver spec Não-objetivos).
- Regra: condição = remetente exato OU domínio (nunca ambos simultaneamente);
  ação = mover para pasta apenas (sem exclusão automática via regra).
- Tokens/senhas **nunca logados em texto claro**.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `mail_organizer/__init__.py`
- Create: `mail_organizer/providers/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_scaffolding.py`

**Interfaces:**
- Produces: importable package `mail_organizer` and `mail_organizer.providers`,
  a working `pytest` setup.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scaffolding.py
def test_package_imports():
    import mail_organizer
    import mail_organizer.providers

    assert mail_organizer.providers is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scaffolding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer'`

- [ ] **Step 3: Create package files and pyproject.toml**

```toml
# pyproject.toml
[project]
name = "mail-organizer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "cryptography>=42.0",
    "google-api-python-client>=2.100",
    "requests>=2.31",
    "imapclient>=3.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# mail_organizer/__init__.py
```

```python
# mail_organizer/providers/__init__.py
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Install the package in editable mode**

Run: `pip install -e ".[dev]"`
Expected: install succeeds, `pytest` available on PATH.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scaffolding.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml mail_organizer tests
git commit -m "chore: scaffold mail_organizer package"
```

---

### Task 2: Crypto module

**Files:**
- Create: `mail_organizer/crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces:
  - `load_or_create_key(key_path: pathlib.Path) -> bytes`
  - `encrypt(plaintext: str, key: bytes) -> bytes`
  - `decrypt(token: bytes, key: bytes) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_crypto.py
import pytest
from mail_organizer.crypto import load_or_create_key, encrypt, decrypt


def test_load_or_create_key_creates_file_on_first_use(tmp_path):
    key_path = tmp_path / "secret.key"
    assert not key_path.exists()

    key = load_or_create_key(key_path)

    assert key_path.exists()
    assert len(key) > 0


def test_load_or_create_key_reuses_existing_key(tmp_path):
    key_path = tmp_path / "secret.key"
    first = load_or_create_key(key_path)
    second = load_or_create_key(key_path)

    assert first == second


def test_encrypt_decrypt_roundtrip(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")

    token = encrypt("super-secret-token", key)
    result = decrypt(token, key)

    assert result == "super-secret-token"
    assert token != b"super-secret-token"


def test_decrypt_fails_with_wrong_key(tmp_path):
    key_a = load_or_create_key(tmp_path / "a.key")
    key_b = load_or_create_key(tmp_path / "b.key")
    token = encrypt("secret", key_a)

    with pytest.raises(Exception):
        decrypt(token, key_b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.crypto'`

- [ ] **Step 3: Implement crypto.py**

```python
# mail_organizer/crypto.py
import pathlib

from cryptography.fernet import Fernet


def load_or_create_key(key_path: pathlib.Path) -> bytes:
    if key_path.exists():
        return key_path.read_bytes()

    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def encrypt(plaintext: str, key: bytes) -> bytes:
    return Fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes, key: bytes) -> str:
    return Fernet(key).decrypt(token).decode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_crypto.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/crypto.py tests/test_crypto.py
git commit -m "feat: add Fernet-based credential encryption"
```

---

### Task 3: SQLite persistence layer

**Files:**
- Create: `mail_organizer/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `mail_organizer.crypto.encrypt`, `mail_organizer.crypto.decrypt`
  (signatures from Task 2).
- Produces:
  - `Database(path: pathlib.Path, key: bytes)` class with:
    - `.init_schema() -> None`
    - `.save_account(account_id: str, provider: str, display_name: str, credentials: dict) -> None`
    - `.get_account(account_id: str) -> dict | None` (decrypted `credentials` field)
    - `.list_accounts() -> list[dict]` (credentials NOT decrypted, for listing UI)
    - `.create_job(job_id: str, account_id: str, total: int) -> None`
    - `.update_job_progress(job_id: str, processed: int, status: str) -> None`
    - `.get_job(job_id: str) -> dict | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
import json

import pytest

from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database


@pytest.fixture
def db(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    database = Database(tmp_path / "app.db", key)
    database.init_schema()
    return database


def test_save_and_get_account_roundtrips_credentials(db):
    db.save_account(
        "acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"}
    )

    account = db.get_account("acc-1")

    assert account["provider"] == "gmail"
    assert account["display_name"] == "rafael@gmail.com"
    assert account["credentials"] == {"refresh_token": "abc123"}


def test_get_account_returns_none_when_missing(db):
    assert db.get_account("does-not-exist") is None


def test_credentials_are_encrypted_at_rest(tmp_path, db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})

    raw_bytes = (tmp_path / "app.db").read_bytes()

    assert b"abc123" not in raw_bytes


def test_list_accounts_does_not_expose_decrypted_credentials(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})

    accounts = db.list_accounts()

    assert accounts[0]["account_id"] == "acc-1"
    assert "credentials" not in accounts[0]


def test_create_and_update_job(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=42)

    job = db.get_job("job-1")
    assert job == {
        "job_id": "job-1",
        "account_id": "acc-1",
        "total": 42,
        "processed": 0,
        "status": "running",
    }

    db.update_job_progress("job-1", processed=10, status="running")
    job = db.get_job("job-1")
    assert job["processed"] == 10

    db.update_job_progress("job-1", processed=42, status="completed")
    job = db.get_job("job-1")
    assert job["status"] == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.db'`

- [ ] **Step 3: Implement db.py**

```python
# mail_organizer/db.py
import json
import pathlib
import sqlite3

from mail_organizer.crypto import decrypt, encrypt

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    credentials_encrypted BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    total INTEGER NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    FOREIGN KEY (account_id) REFERENCES accounts (account_id)
);
"""


class Database:
    def __init__(self, path: pathlib.Path, key: bytes):
        self._key = key
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save_account(
        self, account_id: str, provider: str, display_name: str, credentials: dict
    ) -> None:
        encrypted = encrypt(json.dumps(credentials), self._key)
        self._conn.execute(
            """
            INSERT INTO accounts (account_id, provider, display_name, credentials_encrypted)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                provider = excluded.provider,
                display_name = excluded.display_name,
                credentials_encrypted = excluded.credentials_encrypted
            """,
            (account_id, provider, display_name, encrypted),
        )
        self._conn.commit()

    def get_account(self, account_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "account_id": row["account_id"],
            "provider": row["provider"],
            "display_name": row["display_name"],
            "credentials": json.loads(
                decrypt(row["credentials_encrypted"], self._key)
            ),
        }

    def list_accounts(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT account_id, provider, display_name FROM accounts"
        ).fetchall()
        return [dict(row) for row in rows]

    def create_job(self, job_id: str, account_id: str, total: int) -> None:
        self._conn.execute(
            "INSERT INTO jobs (job_id, account_id, total) VALUES (?, ?, ?)",
            (job_id, account_id, total),
        )
        self._conn.commit()

    def update_job_progress(self, job_id: str, processed: int, status: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET processed = ?, status = ? WHERE job_id = ?",
            (processed, status, job_id),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/db.py tests/test_db.py
git commit -m "feat: add SQLite persistence for accounts and jobs"
```

---

### Task 4: EmailProvider interface and shared types

**Files:**
- Create: `mail_organizer/providers/base.py`
- Test: `tests/providers/__init__.py` (empty)
- Test: `tests/providers/test_base.py`

**Interfaces:**
- Produces:
  - `@dataclass Message` with fields `id: str, folder: str, sender: str,
    subject: str, date: str, snippet: str = "", body_text: str | None = None,
    body_html: str | None = None, headers: dict = field(default_factory=dict)`
  - `@dataclass RuleCondition` with fields `sender: str | None = None, domain: str | None = None`,
    validated in `__post_init__` (exactly one of the two must be set).
  - `class EmailProvider(ABC)` with abstract methods `list_folders`,
    `list_messages`, `get_message`, `move_message`, `delete_message`, and
    concrete defaults `supports_rules() -> bool` (returns `False`) and
    `create_rule(condition: RuleCondition, target_folder: str) -> str`
    (raises `NotImplementedError`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/__init__.py
```

```python
# tests/providers/test_base.py
import pytest

from mail_organizer.providers.base import EmailProvider, Message, RuleCondition


def test_rule_condition_requires_sender_or_domain():
    with pytest.raises(ValueError):
        RuleCondition()


def test_rule_condition_rejects_both_sender_and_domain():
    with pytest.raises(ValueError):
        RuleCondition(sender="a@b.com", domain="b.com")


def test_rule_condition_accepts_sender_only():
    condition = RuleCondition(sender="a@b.com")
    assert condition.sender == "a@b.com"
    assert condition.domain is None


def test_message_defaults():
    message = Message(
        id="1", folder="INBOX", sender="a@b.com", subject="hi", date="2026-01-01"
    )
    assert message.snippet == ""
    assert message.body_text is None
    assert message.headers == {}


class _MinimalProvider(EmailProvider):
    def list_folders(self):
        return []

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


def test_supports_rules_defaults_to_false():
    assert _MinimalProvider().supports_rules() is False


def test_create_rule_raises_not_implemented_by_default():
    provider = _MinimalProvider()
    with pytest.raises(NotImplementedError):
        provider.create_rule(RuleCondition(domain="b.com"), "Promotions")


def test_email_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        EmailProvider()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.providers.base'`

- [ ] **Step 3: Implement base.py**

```python
# mail_organizer/providers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    folder: str
    sender: str
    subject: str
    date: str
    snippet: str = ""
    body_text: str | None = None
    body_html: str | None = None
    headers: dict = field(default_factory=dict)


@dataclass
class RuleCondition:
    sender: str | None = None
    domain: str | None = None

    def __post_init__(self):
        if not self.sender and not self.domain:
            raise ValueError("RuleCondition requires sender or domain")
        if self.sender and self.domain:
            raise ValueError("RuleCondition accepts only one of sender or domain")


class EmailProvider(ABC):
    @abstractmethod
    def list_folders(self) -> list[str]:
        ...

    @abstractmethod
    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        ...

    @abstractmethod
    def get_message(self, message_id: str) -> Message:
        ...

    @abstractmethod
    def move_message(self, message_id: str, target_folder: str) -> None:
        ...

    @abstractmethod
    def delete_message(self, message_id: str) -> None:
        ...

    def supports_rules(self) -> bool:
        return False

    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        raise NotImplementedError(
            f"{type(self).__name__} does not support rule creation"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_base.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/providers/base.py tests/providers/__init__.py tests/providers/test_base.py
git commit -m "feat: add EmailProvider interface and shared Message/RuleCondition types"
```

---

### Task 5: GmailProvider

**Files:**
- Create: `mail_organizer/providers/gmail.py`
- Test: `tests/providers/test_gmail.py`

**Interfaces:**
- Consumes: `EmailProvider`, `Message`, `RuleCondition` from Task 4.
- Produces: `class GmailProvider(EmailProvider)` — constructor
  `GmailProvider(service)` where `service` is an already-authenticated
  `googleapiclient.discovery.Resource` (built outside this class; injected so
  tests use a `MagicMock` instead of real HTTP).

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_gmail.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.gmail import GmailProvider


def _mock_service():
    return MagicMock()


def test_list_folders_returns_label_names():
    service = _mock_service()
    service.users().labels().list().execute.return_value = {
        "labels": [{"name": "INBOX"}, {"name": "Promotions"}]
    }
    provider = GmailProvider(service)

    assert provider.list_folders() == ["INBOX", "Promotions"]


def test_get_message_extracts_headers_and_snippet():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "snippet": "hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "2026-01-01"},
            ]
        },
    }
    provider = GmailProvider(service)

    message = provider.get_message("msg-1")

    assert message.id == "msg-1"
    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.snippet == "hello there"


def test_move_message_calls_modify_with_labels():
    service = _mock_service()
    provider = GmailProvider(service)

    provider.move_message("msg-1", "Promotions")

    service.users().messages().modify.assert_any_call(
        userId="me",
        id="msg-1",
        body={"addLabelIds": ["Promotions"], "removeLabelIds": ["INBOX"]},
    )


def test_delete_message_calls_trash():
    service = _mock_service()
    provider = GmailProvider(service)

    provider.delete_message("msg-1")

    service.users().messages().trash.assert_any_call(userId="me", id="msg-1")


def test_supports_rules_is_true():
    assert GmailProvider(_mock_service()).supports_rules() is True


def test_create_rule_with_sender_condition_calls_filters_create():
    service = _mock_service()
    service.users().settings().filters().create().execute.return_value = {
        "id": "filter-1"
    }
    provider = GmailProvider(service)

    rule_id = provider.create_rule(RuleCondition(sender="a@b.com"), "Promotions")

    assert rule_id == "filter-1"
    service.users().settings().filters().create.assert_any_call(
        userId="me",
        body={
            "criteria": {"from": "a@b.com"},
            "action": {"addLabelIds": ["Promotions"]},
        },
    )


def test_create_rule_with_domain_condition_uses_wildcard():
    service = _mock_service()
    service.users().settings().filters().create().execute.return_value = {
        "id": "filter-2"
    }
    provider = GmailProvider(service)

    provider.create_rule(RuleCondition(domain="newsletter.com"), "Promotions")

    service.users().settings().filters().create.assert_any_call(
        userId="me",
        body={
            "criteria": {"from": "*@newsletter.com"},
            "action": {"addLabelIds": ["Promotions"]},
        },
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_gmail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.providers.gmail'`

- [ ] **Step 3: Implement gmail.py**

```python
# mail_organizer/providers/gmail.py
from mail_organizer.providers.base import EmailProvider, Message, RuleCondition


class GmailProvider(EmailProvider):
    def __init__(self, service):
        self._service = service

    def list_folders(self) -> list[str]:
        result = self._service.users().labels().list(userId="me").execute()
        return [label["name"] for label in result.get("labels", [])]

    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        query_parts = []
        if filters.get("days"):
            query_parts.append(f"newer_than:{filters['days']}d")
        list_kwargs = {"userId": "me"}
        if folder:
            list_kwargs["labelIds"] = [folder]
        if query_parts:
            list_kwargs["q"] = " ".join(query_parts)

        result = self._service.users().messages().list(**list_kwargs).execute()
        return [self.get_message(item["id"]) for item in result.get("messages", [])]

    def get_message(self, message_id: str) -> Message:
        raw = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = {
            h["name"]: h["value"] for h in raw.get("payload", {}).get("headers", [])
        }
        return Message(
            id=raw["id"],
            folder=",".join(raw.get("labelIds", [])),
            sender=headers.get("From", ""),
            subject=headers.get("Subject", ""),
            date=headers.get("Date", ""),
            snippet=raw.get("snippet", ""),
            headers=headers,
        )

    def move_message(self, message_id: str, target_folder: str) -> None:
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [target_folder], "removeLabelIds": ["INBOX"]},
        ).execute()

    def delete_message(self, message_id: str) -> None:
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def supports_rules(self) -> bool:
        return True

    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        sender_pattern = condition.sender or f"*@{condition.domain}"
        body = {
            "criteria": {"from": sender_pattern},
            "action": {"addLabelIds": [target_folder]},
        }
        result = (
            self._service.users()
            .settings()
            .filters()
            .create(userId="me", body=body)
            .execute()
        )
        return result["id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_gmail.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/providers/gmail.py tests/providers/test_gmail.py
git commit -m "feat: add GmailProvider"
```

---

### Task 6: GraphProvider (Outlook/Microsoft Graph)

**Files:**
- Create: `mail_organizer/providers/graph.py`
- Test: `tests/providers/test_graph.py`

**Interfaces:**
- Consumes: `EmailProvider`, `Message`, `RuleCondition` from Task 4.
- Produces: `class GraphProvider(EmailProvider)` — constructor
  `GraphProvider(session)` where `session` is an already-authenticated
  `requests.Session` (its `Authorization` header pre-set outside this class;
  injected so tests use a `MagicMock` instead of real HTTP).

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_graph.py
from unittest.mock import MagicMock

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.graph import GRAPH_BASE, GraphProvider


def _mock_response(json_body):
    response = MagicMock()
    response.json.return_value = json_body
    response.raise_for_status.return_value = None
    return response


def test_list_folders_returns_display_names():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {"value": [{"displayName": "Inbox"}, {"displayName": "Promotions"}]}
    )
    provider = GraphProvider(session)

    assert provider.list_folders() == ["Inbox", "Promotions"]
    session.get.assert_called_with(f"{GRAPH_BASE}/me/mailFolders")


def test_get_message_maps_fields():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "id": "msg-1",
            "parentFolderId": "inbox-id",
            "from": {"emailAddress": {"address": "a@b.com"}},
            "subject": "Hi",
            "receivedDateTime": "2026-01-01T00:00:00Z",
            "bodyPreview": "hello there",
            "body": {"content": "<p>hello</p>"},
        }
    )
    provider = GraphProvider(session)

    message = provider.get_message("msg-1")

    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.body_html == "<p>hello</p>"


def test_move_message_posts_destination_id():
    session = MagicMock()
    session.post.return_value = _mock_response({})
    provider = GraphProvider(session)

    provider.move_message("msg-1", "promotions-id")

    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/messages/msg-1/move",
        json={"destinationId": "promotions-id"},
    )


def test_delete_message_moves_to_deleted_items():
    session = MagicMock()
    session.post.return_value = _mock_response({})
    provider = GraphProvider(session)

    provider.delete_message("msg-1")

    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/messages/msg-1/move",
        json={"destinationId": "deleteditems"},
    )


def test_supports_rules_is_true():
    assert GraphProvider(MagicMock()).supports_rules() is True


def test_create_rule_posts_message_rule():
    session = MagicMock()
    session.post.return_value = _mock_response({"id": "rule-1"})
    provider = GraphProvider(session)

    rule_id = provider.create_rule(RuleCondition(domain="newsletter.com"), "promotions-id")

    assert rule_id == "rule-1"
    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/mailFolders/inbox/messageRules",
        json={
            "displayName": "mail-organizer-newsletter.com",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"senderContains": ["@newsletter.com"]},
            "actions": {"moveToFolder": "promotions-id", "stopProcessingRules": True},
        },
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.providers.graph'`

- [ ] **Step 3: Implement graph.py**

```python
# mail_organizer/providers/graph.py
from mail_organizer.providers.base import EmailProvider, Message, RuleCondition

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphProvider(EmailProvider):
    def __init__(self, session):
        self._session = session

    def list_folders(self) -> list[str]:
        response = self._session.get(f"{GRAPH_BASE}/me/mailFolders")
        response.raise_for_status()
        return [f["displayName"] for f in response.json().get("value", [])]

    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        params = {}
        if filters.get("days"):
            params["$filter"] = f"receivedDateTime ge {filters['days']}"
        response = self._session.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder}/messages", params=params
        )
        response.raise_for_status()
        return [self._to_message(m) for m in response.json().get("value", [])]

    def get_message(self, message_id: str) -> Message:
        response = self._session.get(f"{GRAPH_BASE}/me/messages/{message_id}")
        response.raise_for_status()
        return self._to_message(response.json())

    def _to_message(self, data: dict) -> Message:
        return Message(
            id=data["id"],
            folder=data.get("parentFolderId", ""),
            sender=data.get("from", {}).get("emailAddress", {}).get("address", ""),
            subject=data.get("subject", ""),
            date=data.get("receivedDateTime", ""),
            snippet=data.get("bodyPreview", ""),
            body_html=data.get("body", {}).get("content"),
        )

    def move_message(self, message_id: str, target_folder: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": target_folder},
        )
        response.raise_for_status()

    def delete_message(self, message_id: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": "deleteditems"},
        )
        response.raise_for_status()

    def supports_rules(self) -> bool:
        return True

    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        sender_contains = [condition.sender or f"@{condition.domain}"]
        body = {
            "displayName": f"mail-organizer-{condition.sender or condition.domain}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"senderContains": sender_contains},
            "actions": {
                "moveToFolder": target_folder,
                "stopProcessingRules": True,
            },
        }
        response = self._session.post(
            f"{GRAPH_BASE}/me/mailFolders/inbox/messageRules", json=body
        )
        response.raise_for_status()
        return response.json()["id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_graph.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/providers/graph.py tests/providers/test_graph.py
git commit -m "feat: add GraphProvider for Outlook/Microsoft Graph"
```

---

### Task 7: ImapProvider

**Files:**
- Create: `mail_organizer/providers/imap.py`
- Test: `tests/providers/test_imap.py`

**Interfaces:**
- Consumes: `EmailProvider`, `Message`, `RuleCondition` from Task 4.
- Produces: `class ImapProvider(EmailProvider)` — constructor
  `ImapProvider(client)` where `client` is an already-connected/logged-in
  `imapclient.IMAPClient` (injected so tests use a `MagicMock`).
  `supports_rules()` returns `False`; `create_rule` raises
  `NotImplementedError` (inherited default from `EmailProvider`, not
  overridden).

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_imap.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.imap import ImapProvider


def test_list_folders_returns_folder_names():
    client = MagicMock()
    client.list_folders.return_value = [
        ((), b"/", "INBOX"),
        ((), b"/", "Promotions"),
    ]
    provider = ImapProvider(client)

    assert provider.list_folders() == ["INBOX", "Promotions"]


def test_get_message_parses_envelope_and_body():
    client = MagicMock()
    envelope = MagicMock()
    envelope.from_ = [MagicMock(__str__=lambda self: "a@b.com")]
    envelope.subject = b"Hi"
    envelope.date = "2026-01-01"
    raw_email = (
        b"Content-Type: text/plain\r\n\r\nHello there"
    )
    client.fetch.return_value = {
        42: {b"ENVELOPE": envelope, b"RFC822": raw_email}
    }
    provider = ImapProvider(client)

    message = provider.get_message("42")

    assert message.id == "42"
    assert message.subject == "Hi"
    assert message.body_text == "Hello there"


def test_move_message_calls_client_move():
    client = MagicMock()
    provider = ImapProvider(client)

    provider.move_message("42", "Promotions")

    client.move.assert_called_with([42], "Promotions")


def test_delete_message_moves_to_trash():
    client = MagicMock()
    provider = ImapProvider(client)

    provider.delete_message("42")

    client.move.assert_called_with([42], "Trash")


def test_supports_rules_is_false():
    assert ImapProvider(MagicMock()).supports_rules() is False


def test_create_rule_raises_not_implemented():
    provider = ImapProvider(MagicMock())

    with pytest.raises(NotImplementedError):
        from mail_organizer.providers.base import RuleCondition

        provider.create_rule(RuleCondition(domain="b.com"), "Promotions")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_imap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.providers.imap'`

- [ ] **Step 3: Implement imap.py**

```python
# mail_organizer/providers/imap.py
import email
from email.message import Message as EmailMessage

from mail_organizer.providers.base import EmailProvider, Message


class ImapProvider(EmailProvider):
    def __init__(self, client):
        self._client = client

    def list_folders(self) -> list[str]:
        return [name for _, _, name in self._client.list_folders()]

    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        self._client.select_folder(folder, readonly=True)
        search_criteria = ["ALL"]
        message_ids = self._client.search(search_criteria)
        return [self.get_message(str(msg_id)) for msg_id in message_ids]

    def get_message(self, message_id: str) -> Message:
        data = self._client.fetch([int(message_id)], ["ENVELOPE", "RFC822"])
        entry = data[int(message_id)]
        envelope = entry[b"ENVELOPE"]
        parsed = email.message_from_bytes(entry[b"RFC822"])

        return Message(
            id=message_id,
            folder="",
            sender=str(envelope.from_[0]) if envelope.from_ else "",
            subject=envelope.subject.decode() if envelope.subject else "",
            date=str(envelope.date),
            body_text=self._extract_part(parsed, "text/plain"),
            body_html=self._extract_part(parsed, "text/html"),
        )

    @staticmethod
    def _extract_part(parsed: EmailMessage, content_type: str) -> str | None:
        if parsed.get_content_type() == content_type:
            return parsed.get_payload(decode=True).decode(errors="replace")
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == content_type:
                    return part.get_payload(decode=True).decode(errors="replace")
        return None

    def move_message(self, message_id: str, target_folder: str) -> None:
        self._client.move([int(message_id)], target_folder)

    def delete_message(self, message_id: str) -> None:
        self._client.move([int(message_id)], "Trash")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_imap.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/providers/imap.py tests/providers/test_imap.py
git commit -m "feat: add ImapProvider (no rule support, per spec)"
```

---

### Task 8: AccountService (connects credentials + provider factory)

**Files:**
- Create: `mail_organizer/accounts.py`
- Test: `tests/test_accounts.py`

**Interfaces:**
- Consumes: `Database` (Task 3), `EmailProvider`/`GmailProvider`/
  `GraphProvider`/`ImapProvider` (Tasks 4-7).
- Produces:
  - `class AccountService`, constructor `AccountService(db: Database,
    provider_factories: dict[str, Callable[[dict], EmailProvider]])` — the
    factory dict maps provider name (`"gmail"`, `"graph"`, `"imap"`) to a
    function that takes the decrypted `credentials` dict and returns a ready
    `EmailProvider`. Real factories (building `googleapiclient` services,
    `requests.Session`, `IMAPClient`) are wired in the next plan's FastAPI
    layer, not here — this keeps `AccountService` testable without real
    network clients.
  - `.connect_account(account_id: str, provider: str, display_name: str, credentials: dict) -> None`
  - `.get_provider(account_id: str) -> EmailProvider` (raises `LookupError`
    if the account does not exist)
  - `.list_accounts() -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_accounts.py
import pytest

from mail_organizer.accounts import AccountService
from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database
from mail_organizer.providers.base import EmailProvider


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials

    def list_folders(self):
        return []

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


@pytest.fixture
def service(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    db = Database(tmp_path / "app.db", key)
    db.init_schema()
    return AccountService(db, provider_factories={"fake": _FakeProvider})


def test_connect_account_persists_and_returns_in_list(service):
    service.connect_account("acc-1", "fake", "rafael@example.com", {"token": "x"})

    accounts = service.list_accounts()

    assert accounts[0]["account_id"] == "acc-1"
    assert accounts[0]["provider"] == "fake"


def test_get_provider_builds_provider_from_stored_credentials(service):
    service.connect_account("acc-1", "fake", "rafael@example.com", {"token": "x"})

    provider = service.get_provider("acc-1")

    assert isinstance(provider, _FakeProvider)
    assert provider.credentials == {"token": "x"}


def test_get_provider_raises_lookup_error_for_unknown_account(service):
    with pytest.raises(LookupError):
        service.get_provider("does-not-exist")


def test_get_provider_raises_value_error_for_unknown_provider_type(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    db = Database(tmp_path / "app.db", key)
    db.init_schema()
    service = AccountService(db, provider_factories={})
    service.connect_account("acc-1", "fake", "rafael@example.com", {"token": "x"})

    with pytest.raises(ValueError):
        service.get_provider("acc-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_accounts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.accounts'`

- [ ] **Step 3: Implement accounts.py**

```python
# mail_organizer/accounts.py
from typing import Callable

from mail_organizer.db import Database
from mail_organizer.providers.base import EmailProvider

ProviderFactory = Callable[[dict], EmailProvider]


class AccountService:
    def __init__(self, db: Database, provider_factories: dict[str, ProviderFactory]):
        self._db = db
        self._provider_factories = provider_factories

    def connect_account(
        self, account_id: str, provider: str, display_name: str, credentials: dict
    ) -> None:
        self._db.save_account(account_id, provider, display_name, credentials)

    def list_accounts(self) -> list[dict]:
        return self._db.list_accounts()

    def get_provider(self, account_id: str) -> EmailProvider:
        account = self._db.get_account(account_id)
        if account is None:
            raise LookupError(f"Unknown account: {account_id}")

        factory = self._provider_factories.get(account["provider"])
        if factory is None:
            raise ValueError(f"No provider factory registered for: {account['provider']}")

        return factory(account["credentials"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_accounts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/accounts.py tests/test_accounts.py
git commit -m "feat: add AccountService tying persistence to provider factories"
```

---

### Task 9: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: All tests from Tasks 1-8 PASS (0 failures).

- [ ] **Step 2: Confirm no direct third-party imports outside providers/**

Run (bash/PowerShell — adapt to your shell):
```
grep -rl "googleapiclient\|imapclient" mail_organizer --include="*.py" | grep -v "mail_organizer/providers/"
```
Expected: no output (empty) — confirms provider isolation constraint from the
Global Constraints section.

- [ ] **Step 3: Commit (only if step 2 required fixes; otherwise skip)**

```bash
git add -A
git commit -m "chore: verify provider isolation and full suite green"
```
