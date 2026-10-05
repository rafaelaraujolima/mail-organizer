from urllib.parse import urlencode

import requests

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

GRAPH_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_SCOPE = "offline_access Mail.ReadWrite MailboxSettings.ReadWrite"


class OAuthExchangeError(Exception):
    """Raised when a provider's token endpoint rejects the authorization code."""


def build_gmail_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GMAIL_AUTH_URL}?{urlencode(params)}"


def _post_token_request(session, url: str, data: dict, provider_name: str) -> dict:
    try:
        response = session.post(url, data=data, timeout=10)
    except requests.RequestException as exc:
        raise OAuthExchangeError(f"Falha de rede ao falar com {provider_name}") from exc
    if response.status_code != 200:
        raise OAuthExchangeError(f"{provider_name} rejeitou a troca de código: {response.status_code} {response.text}")
    try:
        return response.json()
    except ValueError as exc:
        raise OAuthExchangeError(f"Resposta inválida de {provider_name}") from exc


def exchange_gmail_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    body = _post_token_request(
        session,
        GMAIL_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
        },
        "Google",
    )

    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise OAuthExchangeError(
            "Google não retornou refresh_token (revogue o acesso em "
            "myaccount.google.com/permissions e tente conectar de novo)"
        )
    return refresh_token


def build_graph_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GRAPH_SCOPE,
        "state": state,
    }
    return f"{GRAPH_AUTH_URL}?{urlencode(params)}"


def exchange_graph_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    body = _post_token_request(
        session,
        GRAPH_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
            "scope": GRAPH_SCOPE,
        },
        "Microsoft",
    )

    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise OAuthExchangeError("Microsoft não retornou refresh_token")
    return refresh_token
