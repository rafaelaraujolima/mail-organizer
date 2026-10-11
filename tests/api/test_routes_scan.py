from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import EmailProvider, Folder, Message
from mail_organizer.providers.errors import ProviderError


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials

    def list_folders(self):
        return [Folder(id="INBOX", name="INBOX")]

    def list_messages(self, folder, filters):
        return [Message(id="msg-1", folder=folder, sender="a@b.com", subject="Hi", date="2026-01-01")]

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


class _FailingListMessagesProvider(_FakeProvider):
    def list_messages(self, folder, filters):
        raise ProviderError("mailbox unreachable")


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingListMessagesProvider}


def test_start_scan_returns_404_for_unknown_account(client):
    response = client.post("/scan", json={"account_id": "does-not-exist", "folder": "INBOX", "filters": {}})

    assert response.status_code == 404


def test_start_scan_returns_502_when_listing_messages_fails(client, db):
    db.save_account("acc-1", "failing", "x", {})

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert response.status_code == 502


def test_start_scan_creates_job_and_runs_it_in_the_background(client, db, monkeypatch):
    db.save_account("acc-1", "fake", "x", {})
    fake_ollama = MagicMock()
    fake_ollama.check_available.side_effect = Exception("no Ollama in tests")
    monkeypatch.setattr("mail_organizer.api.routes_scan.OllamaClient", lambda *a, **kw: fake_ollama)

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert response.json()["total"] == 1

    # TestClient runs BackgroundTasks synchronously before returning the response,
    # so run_scan has already executed with our fake (failing) Ollama client.
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"


def test_get_job_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist")

    assert response.status_code == 404


def test_list_job_proposals_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist/proposals")

    assert response.status_code == 404


def test_list_job_proposals_returns_empty_list_for_job_with_no_proposals(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=0)

    response = client.get("/jobs/job-1/proposals")

    assert response.status_code == 200
    assert response.json() == []


def test_start_scan_persists_the_scanned_folder_on_the_job(client, db, monkeypatch):
    db.save_account("acc-1", "fake", "x", {})
    fake_ollama = MagicMock()
    fake_ollama.check_available.side_effect = Exception("no Ollama in tests")
    monkeypatch.setattr("mail_organizer.api.routes_scan.OllamaClient", lambda *a, **kw: fake_ollama)

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert db.get_job(response.json()["job_id"])["folder"] == "INBOX"
