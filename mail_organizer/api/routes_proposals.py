import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service, get_db
from mail_organizer.apply import apply_proposal
from mail_organizer.db import Database
from mail_organizer.providers.errors import ProviderError
from mail_organizer.sanitize import sanitize_html

router = APIRouter(tags=["proposals"])

# Sync handlers run in a threadpool; without this lock two concurrent approvals
# of the same proposal both pass the "not applied" check. Single-user app, so
# serializing approvals is acceptable.
_APPLY_LOCK = threading.Lock()


def _open_provider(service: AccountService, job: dict):
    # IMAP message ids are per-folder UIDs, so the scanned folder must be selected first.
    provider = service.get_provider(job["account_id"])
    if job.get("folder"):
        provider.select_folder(job["folder"])
    return provider


def _apply_and_record(db: Database, service: AccountService, proposal: dict) -> dict:
    job = db.get_job(proposal["job_id"])
    try:
        provider = _open_provider(service, job)
    except (LookupError, ValueError, ProviderError, OSError) as exc:
        message = (
            "Conta da proposta não encontrada"
            if isinstance(exc, LookupError)
            else f"Falha ao acessar a conta: {exc}"
        )
        db.mark_proposal_applied(proposal["id"], "pending", message)
        return {"success": False, "message": message}

    result = apply_proposal(provider, proposal)
    db.mark_proposal_applied(
        proposal["id"],
        "applied" if result.success else "pending",
        None if result.success else result.message,
    )
    return {"success": result.success, "message": result.message}


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: int, db: Database = Depends(get_db), service: AccountService = Depends(get_account_service)
) -> dict:
    with _APPLY_LOCK:
        proposal = db.get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposta não encontrada")
        if proposal["applied_status"] == "applied":
            raise HTTPException(status_code=409, detail="Proposta já foi aplicada")

        result = _apply_and_record(db, service, proposal)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int, db: Database = Depends(get_db)) -> dict:
    proposal = db.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposta não encontrada")
    if proposal["applied_status"] == "applied":
        raise HTTPException(status_code=409, detail="Proposta já foi aplicada")

    db.mark_proposal_applied(proposal_id, "rejected")
    return {"success": True}


class BatchApproveRequest(BaseModel):
    ids: list[int]


@router.post("/proposals/batch-approve")
def batch_approve(
    body: BatchApproveRequest,
    db: Database = Depends(get_db),
    service: AccountService = Depends(get_account_service),
) -> dict:
    results: dict[str, str] = {}
    for proposal_id in dict.fromkeys(body.ids):
        with _APPLY_LOCK:
            proposal = db.get_proposal(proposal_id)
            if proposal is None:
                results[str(proposal_id)] = "error: proposta não encontrada"
                continue
            if proposal["applied_status"] == "applied":
                results[str(proposal_id)] = "error: já aplicada"
                continue

            outcome = _apply_and_record(db, service, proposal)
        results[str(proposal_id)] = "ok" if outcome["success"] else f"error: {outcome['message']}"

    return results


@router.get("/jobs/{job_id}/messages/{message_id}/content")
def get_message_content(
    job_id: str,
    message_id: str,
    db: Database = Depends(get_db),
    service: AccountService = Depends(get_account_service),
) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    try:
        provider = _open_provider(service, job)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    except (ValueError, ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a conta: {exc}")

    try:
        message = provider.get_message(message_id)
    except (ProviderError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar a mensagem: {exc}")
    return {"html": sanitize_html(message.body_html)}
