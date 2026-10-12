import json
import pathlib
import sqlite3
import threading

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
    error_message TEXT,
    folder TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts (account_id)
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_folder TEXT,
    reason TEXT NOT NULL,
    sender TEXT,
    subject TEXT,
    date TEXT,
    snippet TEXT,
    applied_status TEXT NOT NULL DEFAULT 'pending',
    applied_error TEXT,
    rule_kind TEXT,
    rule_value TEXT,
    rule_match_count INTEGER,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);

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
"""


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


class SchemaOutOfDateError(RuntimeError):
    """The database file is from an older schema version and could not be migrated."""


class Database:
    def __init__(self, path: pathlib.Path, key: bytes):
        self._path = path
        self._key = key
        # check_same_thread=False so the connection survives being used from a
        # worker thread (e.g. FastAPI BackgroundTasks); self._lock serialises writes.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
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
        # Per-connection pragma: SQLite ignores declared FKs unless this is on.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def save_account(
        self, account_id: str, provider: str, display_name: str, credentials: dict
    ) -> None:
        encrypted = encrypt(json.dumps(credentials), self._key)
        with self._lock:
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

    def create_job(self, job_id: str, account_id: str, total: int, folder: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, account_id, total, folder) VALUES (?, ?, ?, ?)",
                (job_id, account_id, total, folder),
            )
            self._conn.commit()

    def update_job_progress(self, job_id: str, processed: int, status: str) -> None:
        with self._lock:
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

    def mark_job_failed(self, job_id: str, error_message: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'failed', error_message = ? WHERE job_id = ?",
                (error_message, job_id),
            )
            self._conn.commit()

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

    def mark_proposal_applied(self, proposal_id: int, status: str, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE proposals SET applied_status = ?, applied_error = ? "
                "WHERE id = ? AND applied_status != 'applied'",
                (status, error, proposal_id),
            )
            self._conn.commit()

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
