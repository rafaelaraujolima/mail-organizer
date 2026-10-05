import imapclient
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from imapclient.exceptions import LoginError

from mail_organizer.oauth import GMAIL_TOKEN_URL, GRAPH_TOKEN_URL
from mail_organizer.providers.errors import ProviderAuthError
from mail_organizer.providers.gmail import GmailProvider
from mail_organizer.providers.graph import GraphProvider
from mail_organizer.providers.imap import ImapProvider


def _refresh_access_token(session, token_url: str, client_id: str, client_secret: str, refresh_token: str) -> str:
    response = session.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise ProviderAuthError(f"Falha ao renovar token de acesso: {response.status_code} {response.text}")
    return response.json()["access_token"]


def make_gmail_provider_factory(client_id: str, client_secret: str, session=None):
    session = session or requests.Session()

    def factory(credentials: dict) -> GmailProvider:
        access_token = _refresh_access_token(
            session, GMAIL_TOKEN_URL, client_id, client_secret, credentials["refresh_token"]
        )
        service = build_google_service("gmail", "v1", credentials=Credentials(token=access_token))
        return GmailProvider(service)

    return factory


def make_graph_provider_factory(client_id: str, client_secret: str, session=None):
    refresh_session = session or requests.Session()

    def factory(credentials: dict) -> GraphProvider:
        access_token = _refresh_access_token(
            refresh_session, GRAPH_TOKEN_URL, client_id, client_secret, credentials["refresh_token"]
        )
        provider_session = requests.Session()
        provider_session.headers["Authorization"] = f"Bearer {access_token}"
        return GraphProvider(provider_session)

    return factory


def imap_provider_factory(credentials: dict) -> ImapProvider:
    client = imapclient.IMAPClient(credentials["host"], port=credentials.get("port", 993), ssl=True)
    try:
        client.login(credentials["username"], credentials["password"])
    except LoginError as exc:
        raise ProviderAuthError(f"Falha ao autenticar IMAP: {exc}") from exc
    return ImapProvider(client)
