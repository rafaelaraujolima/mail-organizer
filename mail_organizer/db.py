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
