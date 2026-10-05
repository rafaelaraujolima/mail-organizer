import importlib
import sys

import pytest


@pytest.fixture
def fresh_main_module(tmp_path, monkeypatch):
    """Import mail_organizer.api.main fresh, pointed at a throwaway data dir."""
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    yield module
    module.db.close()
    sys.modules.pop("mail_organizer.api.main", None)


def test_main_builds_a_fastapi_app(fresh_main_module):
    from fastapi import FastAPI

    assert isinstance(fresh_main_module.app, FastAPI)


def test_main_registers_imap_but_not_gmail_when_client_id_missing(fresh_main_module):
    assert "imap" in fresh_main_module.provider_factories
    assert "gmail" not in fresh_main_module.provider_factories


def test_main_registers_gmail_when_client_id_and_secret_present(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    try:
        assert "gmail" in module.provider_factories
        assert "gmail" in module.oauth_config
        assert module.oauth_config["gmail"]["redirect_uri"] == "http://localhost:8000/accounts/gmail/callback"
    finally:
        module.db.close()
        sys.modules.pop("mail_organizer.api.main", None)


def test_main_strips_trailing_slash_from_app_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_BASE_URL", "https://mail.example.com/")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    try:
        assert module.oauth_config["gmail"]["redirect_uri"] == "https://mail.example.com/accounts/gmail/callback"
    finally:
        module.db.close()
        sys.modules.pop("mail_organizer.api.main", None)


def test_main_allows_localhost_and_the_app_base_url_host(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_BASE_URL", "https://mail.example.com:8443/")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    try:
        client = TestClient(module.app)
        assert client.get("/accounts", headers={"Host": "mail.example.com"}).status_code == 200
        assert client.get("/accounts", headers={"Host": "127.0.0.1:8000"}).status_code == 200
        assert client.get("/accounts", headers={"Host": "evil.example"}).status_code == 400
    finally:
        module.db.close()
        sys.modules.pop("mail_organizer.api.main", None)
