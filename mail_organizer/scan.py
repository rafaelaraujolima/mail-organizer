from mail_organizer.db import Database
from mail_organizer.heuristics import analyze_message
from mail_organizer.llm import OllamaClient, OllamaUnavailableError
from mail_organizer.proposals import build_proposal
from mail_organizer.providers.base import EmailProvider, Message
from mail_organizer.providers.errors import ProviderError


def run_scan(
    db: Database,
    provider: EmailProvider,
    llm_client: OllamaClient,
    job_id: str,
    messages: list[Message],
) -> None:
    try:
        llm_client.check_available()
    except OllamaUnavailableError as exc:
        db.mark_job_failed(job_id, str(exc))
        return

    try:
        existing_folders = [folder.name for folder in provider.list_folders()]
    except ProviderError as exc:
        db.mark_job_failed(job_id, f"Falha ao acessar a caixa: {exc}")
        return

    processed = 0
    for message in messages:
        try:
            heuristic_result = analyze_message(message)
            classification = llm_client.classify(message, existing_folders, heuristic_result.flags)
            proposal = build_proposal(message, heuristic_result, classification)
            db.add_proposal(job_id, proposal.message_id, proposal.action, proposal.target_folder, proposal.reason)
        except Exception as exc:
            db.add_proposal(job_id, message.id, "error", None, f"Erro ao analisar: {exc}")
        finally:
            processed += 1
            db.update_job_progress(job_id, processed, "running")

    db.update_job_progress(job_id, processed, "completed")
