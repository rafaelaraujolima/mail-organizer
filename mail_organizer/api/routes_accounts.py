import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service
from mail_organizer.factories import imap_provider_factory
from mail_organizer.providers.errors import ProviderError
from mail_organizer.oauth import (
    OAuthExchangeError,
    build_gmail_authorize_url,
    build_graph_authorize_url,
    exchange_gmail_code,
    exchange_graph_code,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


class ImapConnectRequest(BaseModel):
    display_name: str
    host: str
    port: int = 993
    username: str
    password: str


@router.post("/imap", status_code=201)
def connect_imap(
    body: ImapConnectRequest, service: AccountService = Depends(get_account_service)
) -> dict:
    credentials = {
        "host": body.host, "port": body.port, "username": body.username, "password": body.password,
    }
    try:
        imap_provider_factory(credentials)
    except (ProviderError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível conectar: {exc}")

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "imap", body.display_name, credentials)
    return {"account_id": account_id}


@router.get("")
def list_accounts(service: AccountService = Depends(get_account_service)) -> list[dict]:
    return service.list_accounts()


@router.get("/{account_id}/folders")
def list_folders(account_id: str, service: AccountService = Depends(get_account_service)) -> list[dict]:
    try:
        provider = service.get_provider(account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    except (ValueError, ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a conta: {exc}")

    try:
        folders = provider.list_folders()
    except (ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a caixa: {exc}")

    return [{"id": f.id, "name": f.name} for f in folders]


def _oauth_config(request: Request, provider: str) -> dict:
    config = request.app.state.oauth_config.get(provider)
    if not config or not config.get("client_id") or not config.get("client_secret"):
        raise HTTPException(
            status_code=503,
            detail=f"OAuth para {provider} não configurado (defina as variáveis de ambiente correspondentes)",
        )
    return config


def _new_state(request: Request) -> str:
    state = secrets.token_urlsafe(16)
    request.app.state.oauth_states.add(state)
    return state


def _consume_state(request: Request, state: str | None) -> None:
    # Single use; checked before any code exchange.
    if not state or state not in request.app.state.oauth_states:
        raise HTTPException(status_code=400, detail="state inválido ou ausente")
    request.app.state.oauth_states.discard(state)


@router.get("/gmail/authorize")
def gmail_authorize(request: Request):
    config = _oauth_config(request, "gmail")
    state = _new_state(request)
    url = build_gmail_authorize_url(config["client_id"], config["redirect_uri"], state)
    return RedirectResponse(url)


@router.get("/gmail/callback")
def gmail_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    display_name: str = "Gmail",
    service: AccountService = Depends(get_account_service),
) -> dict:
    _consume_state(request, state)
    if error or not code:
        raise HTTPException(status_code=400, detail=f"Autorização Google não concluída: {error or 'código ausente'}")

    config = _oauth_config(request, "gmail")
    try:
        refresh_token = exchange_gmail_code(
            config["session"], config["client_id"], config["client_secret"], config["redirect_uri"], code
        )
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "gmail", display_name, {"refresh_token": refresh_token})
    return {"account_id": account_id}


@router.get("/graph/authorize")
def graph_authorize(request: Request):
    config = _oauth_config(request, "graph")
    state = _new_state(request)
    url = build_graph_authorize_url(config["client_id"], config["redirect_uri"], state)
    return RedirectResponse(url)


@router.get("/graph/callback")
def graph_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    display_name: str = "Outlook",
    service: AccountService = Depends(get_account_service),
) -> dict:
    _consume_state(request, state)
    if error or not code:
        raise HTTPException(status_code=400, detail=f"Autorização Microsoft não concluída: {error or 'código ausente'}")

    config = _oauth_config(request, "graph")
    try:
        refresh_token = exchange_graph_code(
            config["session"], config["client_id"], config["client_secret"], config["redirect_uri"], code
        )
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "graph", display_name, {"refresh_token": refresh_token})
    return {"account_id": account_id}
