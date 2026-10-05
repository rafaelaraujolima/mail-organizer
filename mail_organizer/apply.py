from dataclasses import dataclass

from mail_organizer.providers.base import EmailProvider
from mail_organizer.providers.errors import ProviderError


@dataclass
class ApplyResult:
    success: bool
    message: str


def apply_proposal(provider: EmailProvider, proposal: dict) -> ApplyResult:
    action = proposal["action"]

    if action == "move":
        target_name = proposal["target_folder"]
        try:
            folders = provider.list_folders()
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao listar pastas: {exc}")

        matching = [f for f in folders if f.name == target_name]
        if not matching:
            return ApplyResult(success=False, message=f"Pasta '{target_name}' não existe mais na caixa")

        try:
            provider.move_message(proposal["message_id"], matching[0].id)
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao mover mensagem: {exc}")
        return ApplyResult(success=True, message=f"Movido para {target_name}")

    if action == "flag_delete":
        try:
            provider.delete_message(proposal["message_id"])
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao excluir mensagem: {exc}")
        return ApplyResult(success=True, message="Movido para a Lixeira")

    # "keep" and "error" proposals require no provider call.
    return ApplyResult(success=True, message="Nenhuma ação necessária")
