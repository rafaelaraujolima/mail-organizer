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
