from unittest.mock import MagicMock

import pytest

from mail_organizer.oauth import (
    OAuthExchangeError,
    build_gmail_authorize_url,
    build_graph_authorize_url,
    exchange_gmail_code,
    exchange_graph_code,
)


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


def test_build_gmail_authorize_url_includes_required_params():
    url = build_gmail_authorize_url("client-123", "http://localhost:8000/cb", "state-abc")

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcb" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state-abc" in url


def test_exchange_gmail_code_posts_and_returns_refresh_token():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"refresh_token": "rt-1", "access_token": "at-1"})

    token = exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "auth-code")

    assert token == "rt-1"
    call_kwargs = session.post.call_args.kwargs
    assert call_kwargs["data"]["grant_type"] == "authorization_code"
    assert call_kwargs["data"]["code"] == "auth-code"


def test_exchange_gmail_code_raises_on_non_200():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=400, text="invalid_grant")

    with pytest.raises(OAuthExchangeError):
        exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "bad-code")


def test_exchange_gmail_code_raises_when_refresh_token_missing():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "at-1"})

    with pytest.raises(OAuthExchangeError):
        exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "auth-code")


def test_build_graph_authorize_url_includes_required_params():
    url = build_graph_authorize_url("client-456", "http://localhost:8000/cb2", "state-xyz")

    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "client_id=client-456" in url
    assert "state=state-xyz" in url
    assert "offline_access" in url


def test_exchange_graph_code_posts_and_returns_refresh_token():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"refresh_token": "rt-2", "access_token": "at-2"})

    token = exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "auth-code")

    assert token == "rt-2"


def test_exchange_graph_code_raises_on_non_200():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=401, text="invalid_client")

    with pytest.raises(OAuthExchangeError):
        exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "bad-code")


def test_exchange_graph_code_raises_when_refresh_token_missing():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "at-2"})

    with pytest.raises(OAuthExchangeError):
        exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "auth-code")


@pytest.mark.parametrize("exchange", [exchange_gmail_code, exchange_graph_code])
def test_exchange_maps_network_error_to_oauth_exchange_error(exchange):
    import requests

    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("down")

    with pytest.raises(OAuthExchangeError):
        exchange(session, "cid", "secret", "http://x/cb", "code")


@pytest.mark.parametrize("exchange", [exchange_gmail_code, exchange_graph_code])
def test_exchange_maps_non_json_200_to_oauth_exchange_error(exchange):
    session = MagicMock()
    response = _mock_response()
    response.json.side_effect = ValueError("not json")
    session.post.return_value = response

    with pytest.raises(OAuthExchangeError):
        exchange(session, "cid", "secret", "http://x/cb", "code")
