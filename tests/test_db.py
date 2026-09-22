import sqlite3

import pytest

from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database


@pytest.fixture
def db(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    with Database(tmp_path / "app.db", key) as database:
        database.init_schema()
        yield database


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
        "error_message": None,
    }

    db.update_job_progress("job-1", processed=10, status="running")
    job = db.get_job("job-1")
    assert job["processed"] == 10

    db.update_job_progress("job-1", processed=42, status="completed")
    job = db.get_job("job-1")
    assert job["status"] == "completed"


def test_foreign_keys_pragma_is_enabled(db):
    (enabled,) = db._conn.execute("PRAGMA foreign_keys").fetchone()

    assert enabled == 1


def test_foreign_key_constraint_is_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.create_job("job-1", "no-such-account", total=1)


def test_database_works_as_context_manager(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")

    with Database(tmp_path / "app.db", key) as db:
        db.init_schema()
        db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "x"})
        assert db.get_account("acc-1")["provider"] == "gmail"

    with pytest.raises(sqlite3.ProgrammingError):
        db.list_accounts()


def test_close_closes_the_connection(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    db = Database(tmp_path / "app.db", key)
    db.init_schema()

    db.close()

    with pytest.raises(sqlite3.ProgrammingError):
        db.list_accounts()


def test_mark_job_failed_sets_status_and_error_message(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=10)

    db.mark_job_failed("job-1", "Ollama não está rodando")

    job = db.get_job("job-1")
    assert job["status"] == "failed"
    assert job["error_message"] == "Ollama não está rodando"


def test_get_job_error_message_defaults_to_none(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=10)

    job = db.get_job("job-1")

    assert job["error_message"] is None


def test_add_and_list_proposals_roundtrip_in_insertion_order(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=2)

    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")
    db.add_proposal("job-1", "msg-2", "flag_delete", None, "spf_fail")

    proposals = db.list_proposals("job-1")

    assert proposals == [
        {"message_id": "msg-1", "action": "move", "target_folder": "Promotions", "reason": "Newsletter"},
        {"message_id": "msg-2", "action": "flag_delete", "target_folder": None, "reason": "spf_fail"},
    ]


def test_list_proposals_empty_for_job_with_no_proposals(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=0)

    assert db.list_proposals("job-1") == []
