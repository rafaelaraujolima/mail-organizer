import uuid

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service, get_db
from mail_organizer.db import Database
from mail_organizer.llm import OllamaClient
from mail_organizer.providers.errors import ProviderError
from mail_organizer.scan import run_scan

router = APIRouter(tags=["scan"])


class ScanRequest(BaseModel):
    account_id: str
    folder: str
    filters: dict = {}


@router.post("/scan", status_code=201)
def start_scan(
    body: ScanRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: AccountService = Depends(get_account_service),
    db: Database = Depends(get_db),
) -> dict:
    try:
        provider = service.get_provider(body.account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    except (ValueError, ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a conta: {exc}")

    try:
        messages = provider.list_messages(body.folder, body.filters)
    except (ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao listar mensagens: {exc}")

    job_id = str(uuid.uuid4())
    db.create_job(job_id, body.account_id, total=len(messages), folder=body.folder)

    llm_client = OllamaClient(
        requests.Session(), base_url=request.app.state.ollama_base_url, model=request.app.state.ollama_model
    )
    background_tasks.add_task(run_scan, db, provider, llm_client, job_id, messages)

    return {"job_id": job_id, "total": len(messages)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Database = Depends(get_db)) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


@router.get("/jobs/{job_id}/proposals")
def list_job_proposals(job_id: str, db: Database = Depends(get_db)) -> list[dict]:
    if db.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return db.list_proposals(job_id)
