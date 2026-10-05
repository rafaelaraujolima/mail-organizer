from unittest.mock import MagicMock, patch

import pytest
from imapclient.exceptions import LoginError

from mail_organizer.factories import (
    imap_provider_factory,
    make_gmail_provider_factory,
    make_graph_provider_factory,
)
from mail_organizer.providers.errors import ProviderAuthError
from mail_organizer.providers.gmail import GmailProvider
from mail_organizer.providers.graph import GraphProvider
from mail_organizer.providers.imap import ImapProvider


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


def test_gmail_factory_refreshes_token_and_builds_provider():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "fresh-at"})
    factory = make_gmail_provider_factory("cid", "secret", session=session)

    with patch("mail_organizer.factories.build_google_service") as mock_build, \
         patch("mail_organizer.factories.Credentials") as mock_credentials:
        mock_build.return_value = "the-service"

        provider = factory({"refresh_token": "rt-1"})

    mock_credentials.assert_called_once_with(token="fresh-at")
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_credentials.return_value)
    assert isinstance(provider, GmailProvider)


def test_gmail_factory_raises_provider_auth_error_when_refresh_fails():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=400, text="invalid_grant")
    factory = make_gmail_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "expired"})


def test_graph_factory_refreshes_token_and_builds_provider_with_bearer_header():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "fresh-graph-at"})
    factory = make_graph_provider_factory("cid", "secret", session=session)

    provider = factory({"refresh_token": "rt-2"})

    assert isinstance(provider, GraphProvider)
    assert provider._session.headers["Authorization"] == "Bearer fresh-graph-at"


def test_graph_factory_raises_provider_auth_error_when_refresh_fails():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=401, text="invalid_client")
    factory = make_graph_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "expired"})


def test_imap_provider_factory_logs_in_and_builds_provider():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_client = MagicMock()
        mock_imap_cls.return_value = mock_client

        provider = imap_provider_factory(
            {"host": "imap.example.com", "port": 993, "username": "a@example.com", "password": "app-pw"}
        )

    mock_imap_cls.assert_called_once_with("imap.example.com", port=993, ssl=True)
    mock_client.login.assert_called_once_with("a@example.com", "app-pw")
    assert isinstance(provider, ImapProvider)


def test_imap_provider_factory_raises_provider_auth_error_on_bad_login():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_client = MagicMock()
        mock_client.login.side_effect = LoginError("bad credentials")
        mock_imap_cls.return_value = mock_client

        with pytest.raises(ProviderAuthError):
            imap_provider_factory(
                {"host": "imap.example.com", "port": 993, "username": "a@example.com", "password": "wrong"}
            )


def test_imap_provider_factory_defaults_port_to_993():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_imap_cls.return_value = MagicMock()

        imap_provider_factory({"host": "imap.example.com", "username": "a@example.com", "password": "pw"})

    mock_imap_cls.assert_called_once_with("imap.example.com", port=993, ssl=True)


def test_refresh_maps_network_error_to_provider_auth_error_without_secrets():
    import requests

    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("boom rt-secret")
    factory = make_gmail_provider_factory("cid", "csecret", session=session)

    with pytest.raises(ProviderAuthError) as excinfo:
        factory({"refresh_token": "rt-secret"})

    assert str(excinfo.value) == "Falha de rede ao renovar token de acesso"


def test_refresh_maps_non_json_200_to_provider_auth_error():
    session = MagicMock()
    response = _mock_response()
    response.json.side_effect = ValueError("not json")
    session.post.return_value = response
    factory = make_graph_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "rt"})


def test_refresh_maps_missing_access_token_to_provider_auth_error():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"other": "x"})
    factory = make_gmail_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "rt"})
