from dataclasses import dataclass

from mail_organizer.heuristics import HeuristicResult
from mail_organizer.llm import ClassificationResult
from mail_organizer.providers.base import Message


@dataclass
class Proposal:
    message_id: str
    action: str  # "move" | "flag_delete" | "keep"
    target_folder: str | None
    reason: str


def build_proposal(
    message: Message, heuristic_result: HeuristicResult, classification: ClassificationResult
) -> Proposal:
    if heuristic_result.is_suspicious or classification.suspicious:
        reasons = list(heuristic_result.flags)
        if classification.suspicious and classification.reason:
            reasons.append(classification.reason)
        return Proposal(
            message_id=message.id,
            action="flag_delete",
            target_folder=None,
            reason="; ".join(reasons) if reasons else "Sinalizado como suspeito pela IA",
        )

    if classification.folder:
        return Proposal(
            message_id=message.id,
            action="move",
            target_folder=classification.folder,
            reason=classification.reason or f"Sugestão de organização: mover para {classification.folder}",
        )

    return Proposal(
        message_id=message.id,
        action="keep",
        target_folder=None,
        reason=classification.reason or "Nenhuma ação sugerida",
    )
