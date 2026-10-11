from dataclasses import dataclass

from mail_organizer.providers.base import EmailProvider, RuleCondition
from mail_organizer.providers.errors import ProviderError
from mail_organizer.rules import is_system_folder


@dataclass
class ApplyResult:
    success: bool
    message: str
    rule_id: str | None = None


def _apply_rule(provider: EmailProvider, proposal: dict) -> ApplyResult:
    if not provider.supports_rules():
        return ApplyResult(success=False, message="Este provedor não suporta a criação de regras")

    kind = proposal.get("rule_kind")
    value = proposal.get("rule_value")
    target_name = proposal.get("target_folder")
    if kind not in ("sender", "domain") or not value or not target_name:
        return ApplyResult(success=False, message="Proposta de regra incompleta")
    if is_system_folder(target_name):
        return ApplyResult(
            success=False, message=f"Regras não podem mover para a pasta de sistema '{target_name}'"
        )

    try:
        folders = provider.list_folders()
    except ProviderError as exc:
        return ApplyResult(success=False, message=f"Falha ao listar pastas: {exc}")

    matching = [f for f in folders if f.name == target_name]
    if not matching:
        return ApplyResult(success=False, message=f"Pasta '{target_name}' não existe mais na caixa")

    condition = RuleCondition(sender=value) if kind == "sender" else RuleCondition(domain=value)
    try:
        rule_id = provider.create_rule(condition, matching[0].id)
    except NotImplementedError:
        return ApplyResult(success=False, message="Este provedor não suporta a criação de regras")
    except ProviderError as exc:
        return ApplyResult(success=False, message=f"Falha ao criar a regra: {exc}")
    return ApplyResult(success=True, message=f"Regra criada: {value} → {target_name}", rule_id=rule_id)


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

    if action == "create_rule":
        return _apply_rule(provider, proposal)

    # "keep" and "error" proposals require no provider call.
    if action in ("keep", "error"):
        return ApplyResult(success=True, message="Nenhuma ação necessária")

    return ApplyResult(success=False, message=f"Ação desconhecida: {action}")
