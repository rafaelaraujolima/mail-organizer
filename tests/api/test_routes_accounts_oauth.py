from unittest.mock import MagicMock

import pytest

from mail_organizer.api.app import create_app
from fastapi.testclient import TestClient


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


@pytest.fixture
def oauth_session():
    return MagicMock()


@pytest.fixture
def client(db, oauth_session):
    app = create_app(
        db,
        provider_factories={},
        oauth_config={
            "gmail": {"client_id": "gcid", "client_secret": "gsecret", "redirect_uri": "http://x/accounts/gmail/callback", "session": oauth_session},
        },
    )
    return TestClient(app, follow_redirects=False)


def test_gmail_authorize_redirects_to_google_with_client_id(client):
    response = client.get("/accounts/gmail/authorize")

    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]
    assert "client_id=gcid" in response.headers["location"]


def test_graph_authorize_returns_503_when_not_configured(client):
    response = client.get("/accounts/graph/authorize", follow_redirects=False)

    assert response.status_code == 503


def test_gmail_callback_with_error_param_returns_400(client):
    response = client.get("/accounts/gmail/callback?error=access_denied")

    assert response.status_code == 400


def test_gmail_callback_missing_code_returns_400(client):
    response = client.get("/accounts/gmail/callback")

    assert response.status_code == 400


def test_gmail_callback_success_persists_account(client, oauth_session):
    oauth_session.post.return_value = _mock_response(json_body={"refresh_token": "rt-1"})

    response = client.get("/accounts/gmail/callback?code=auth-code&display_name=My+Gmail")

    assert response.status_code == 200
    account_id = response.json()["account_id"]
    accounts = client.get("/accounts").json()
    assert any(a["account_id"] == account_id and a["provider"] == "gmail" for a in accounts)


def test_gmail_callback_returns_502_when_exchange_fails(client, oauth_session):
    oauth_session.post.return_value = _mock_response(status_code=400, text="invalid_grant")

    response = client.get("/accounts/gmail/callback?code=bad-code")

    assert response.status_code == 502
