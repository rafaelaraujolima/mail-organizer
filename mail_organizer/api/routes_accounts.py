import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service
from mail_organizer.factories import imap_provider_factory
from mail_organizer.providers.errors import ProviderError

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

    try:
        folders = provider.list_folders()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a caixa: {exc}")

    return [{"id": f.id, "name": f.name} for f in folders]
