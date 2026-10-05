import pytest
from fastapi.testclient import TestClient

from mail_organizer.api.app import create_app
from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database


@pytest.fixture
def db(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    database = Database(tmp_path / "app.db", key)
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def provider_factories():
    """Override in a test module to inject fakes for specific providers."""
    return {}


@pytest.fixture
def app(db, provider_factories):
    return create_app(db, provider_factories)


@pytest.fixture
def client(app):
    return TestClient(app, headers={"X-Requested-With": "mail-organizer"})
