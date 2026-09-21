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
