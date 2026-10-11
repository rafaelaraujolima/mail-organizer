from mail_organizer.db import Database
from mail_organizer.heuristics import analyze_message
from mail_organizer.llm import ClassificationResult, OllamaClient, OllamaUnavailableError
from mail_organizer.proposals import build_proposal
from mail_organizer.providers.base import EmailProvider, Message
from mail_organizer.providers.errors import ProviderError
from mail_organizer.rules import detect_rule_candidates


def _propose_rules(db: Database, provider: EmailProvider, job_id: str, threshold: int) -> None:
    if not provider.supports_rules():
        return
    account_id = db.get_job(job_id)["account_id"]
    existing = [(rule["kind"], rule["value"]) for rule in db.list_applied_rules(account_id)]
    for candidate in detect_rule_candidates(db.list_proposals(job_id), existing, threshold):
        db.add_proposal(
            job_id, "", "create_rule", candidate.folder,
            f"{candidate.count} emails deste lote vão para {candidate.folder}",
            sender=candidate.value, rule_kind=candidate.kind,
            rule_value=candidate.value, rule_match_count=candidate.count,
        )


def run_scan(
    db: Database,
    provider: EmailProvider,
    llm_client: OllamaClient,
    job_id: str,
    messages: list[Message],
    rule_threshold: int = 3,
) -> None:
    # Everything below is wrapped in a backstop: no exception -- anticipated
    # or not -- should ever be able to leave run_scan without db.mark_job_failed
    # or a final db.update_job_progress(..., "completed") having been called.
    # Otherwise the job is stuck in "running" forever and the frontend, which
    # polls job status, shows an eternal spinner.
    try:
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
            preview = dict(
                sender=message.sender, subject=message.subject, date=message.date,
                snippet=(message.snippet or "")[:200],
            )
            try:
                heuristic_result = analyze_message(message)
                classification = llm_client.classify(message, existing_folders, heuristic_result.flags)
                if classification.folder and classification.folder not in existing_folders:
                    # The LLM can hallucinate a folder name that was never in
                    # the list it was given. Don't let that flow into the
                    # proposal -- treat it as no suggestion instead.
                    classification = ClassificationResult(
                        folder=None, suspicious=classification.suspicious, reason=classification.reason
                    )
                proposal = build_proposal(message, heuristic_result, classification)
                db.add_proposal(
                    job_id, proposal.message_id, proposal.action, proposal.target_folder, proposal.reason,
                    **preview,
                )
            except Exception as exc:
                try:
                    db.add_proposal(job_id, message.id, "error", None, f"Erro ao analisar: {exc}", **preview)
                except Exception:
                    # Recording the failure itself failed (e.g. transient DB error).
                    # Swallow it so the scan keeps going and still reaches
                    # "completed" below, instead of leaving the job stuck "running".
                    pass
            finally:
                processed += 1
                db.update_job_progress(job_id, processed, "running")

        try:
            _propose_rules(db, provider, job_id, rule_threshold)
        except Exception:
            # Rule proposals are an extra: a failure here must never turn a
            # finished scan into a failed one.
            pass

        db.update_job_progress(job_id, processed, "completed")
    except Exception as exc:
        db.mark_job_failed(job_id, f"Falha inesperada durante o scan: {exc}")
