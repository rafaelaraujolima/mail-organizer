import pytest

from mail_organizer.providers.base import EmailProvider, Folder
from mail_organizer.providers.errors import ProviderAuthError, ProviderError


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials

    def list_folders(self):
        return [Folder(id="INBOX", name="INBOX"), Folder(id="Label_7", name="Promotions")]

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


class _FailingFolderProvider(_FakeProvider):
    def list_folders(self):
        raise ProviderError("token expired")


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingFolderProvider}


def test_connect_imap_verifies_credentials_and_persists_account(client, monkeypatch):
    monkeypatch.setattr(
        "mail_organizer.api.routes_accounts.imap_provider_factory",
        lambda credentials: _FakeProvider(credentials),
    )

    response = client.post(
        "/accounts/imap",
        json={"display_name": "iCloud", "host": "imap.mail.me.com", "port": 993, "username": "a@icloud.com", "password": "app-pw"},
    )

    assert response.status_code == 201
    account_id = response.json()["account_id"]
    accounts = client.get("/accounts").json()
    assert any(a["account_id"] == account_id and a["provider"] == "imap" for a in accounts)


def test_list_accounts_never_exposes_the_imap_password(client, monkeypatch):
    monkeypatch.setattr(
        "mail_organizer.api.routes_accounts.imap_provider_factory",
        lambda credentials: _FakeProvider(credentials),
    )
    client.post(
        "/accounts/imap",
        json={"display_name": "iCloud", "host": "imap.mail.me.com", "port": 993, "username": "a@icloud.com", "password": "s3cret-pw"},
    )

    response = client.get("/accounts")

    assert response.status_code == 200
    assert response.json() != []
    assert "s3cret-pw" not in response.text


def test_connect_imap_rejects_bad_credentials_without_saving(client, monkeypatch):
    def _raise(credentials):
        raise ProviderError("login failed")

    monkeypatch.setattr("mail_organizer.api.routes_accounts.imap_provider_factory", _raise)

    response = client.post(
        "/accounts/imap",
        json={"display_name": "iCloud", "host": "imap.mail.me.com", "port": 993, "username": "a@icloud.com", "password": "wrong"},
    )

    assert response.status_code == 400
    assert client.get("/accounts").json() == []


def test_connect_imap_rejects_unreachable_host_without_saving(client, monkeypatch):
    def _raise(credentials):
        raise OSError("name or service not known")

    monkeypatch.setattr("mail_organizer.api.routes_accounts.imap_provider_factory", _raise)

    response = client.post(
        "/accounts/imap",
        json={"display_name": "x", "host": "nope.invalid", "port": 993, "username": "u", "password": "p"},
    )

    assert response.status_code == 400
    assert client.get("/accounts").json() == []


def test_list_folders_returns_provider_folders(client, db):
    db.save_account("acc-1", "fake", "x", {})

    response = client.get("/accounts/acc-1/folders")

    assert response.status_code == 200
    assert response.json() == [{"id": "INBOX", "name": "INBOX"}, {"id": "Label_7", "name": "Promotions"}]


def test_list_folders_returns_404_for_unknown_account(client):
    response = client.get("/accounts/does-not-exist/folders")

    assert response.status_code == 404


def test_list_folders_returns_502_on_provider_error(client, db):
    db.save_account("acc-1", "failing", "x", {})

    response = client.get("/accounts/acc-1/folders")

    assert response.status_code == 502
    assert "token expired" in response.json()["detail"]


def _auth_failing_factory(credentials):
    raise ProviderAuthError("token refresh failed")


class _TimeoutProvider(_FakeProvider):
    def list_folders(self):
        raise TimeoutError("slow")

    def list_messages(self, folder, filters):
        raise TimeoutError("slow")


@pytest.fixture
def broken_client(db):
    from fastapi.testclient import TestClient

    from mail_organizer.api.app import create_app

    factories = {"authfail": _auth_failing_factory, "timeout": _TimeoutProvider}
    return TestClient(create_app(db, factories), headers={"X-Requested-With": "mail-organizer"})


def test_list_folders_returns_502_when_factory_raises_auth_error(broken_client, db):
    db.save_account("acc-1", "authfail", "x", {})

    response = broken_client.get("/accounts/acc-1/folders")

    assert response.status_code == 502


def test_list_folders_returns_502_when_provider_type_has_no_factory(broken_client, db):
    db.save_account("acc-1", "nonexistent", "x", {})

    response = broken_client.get("/accounts/acc-1/folders")

    assert response.status_code == 502


def test_list_folders_returns_502_on_oserror_from_provider(broken_client, db):
    db.save_account("acc-1", "timeout", "x", {})

    response = broken_client.get("/accounts/acc-1/folders")

    assert response.status_code == 502


def test_scan_returns_502_and_creates_no_job_when_factory_fails(broken_client, db):
    db.save_account("acc-1", "authfail", "x", {})
    db.save_account("acc-2", "nonexistent", "x", {})
    db.save_account("acc-3", "timeout", "x", {})

    for account_id in ("acc-1", "acc-2", "acc-3"):
        response = broken_client.post("/scan", json={"account_id": account_id, "folder": "INBOX", "filters": {}})
        assert response.status_code == 502

    assert db._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
