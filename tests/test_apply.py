from unittest.mock import MagicMock

from mail_organizer.apply import ApplyResult, apply_proposal
from mail_organizer.providers.base import Folder
from mail_organizer.providers.errors import ProviderError


def _proposal(**overrides) -> dict:
    defaults = dict(id=1, job_id="job-1", message_id="msg-1", action="move", target_folder="Promotions", reason="r")
    defaults.update(overrides)
    return defaults


def test_apply_move_resolves_folder_name_to_id_and_calls_move_message():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX"), Folder(id="Label_7", name="Promotions")]

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result == ApplyResult(success=True, message="Movido para Promotions")
    provider.move_message.assert_called_once_with("msg-1", "Label_7")


def test_apply_move_fails_clearly_when_folder_name_not_found():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX")]

    result = apply_proposal(provider, _proposal(action="move", target_folder="Ghost Folder"))

    assert result.success is False
    assert "Ghost Folder" in result.message
    provider.move_message.assert_not_called()


def test_apply_move_fails_when_list_folders_raises_provider_error():
    provider = MagicMock()
    provider.list_folders.side_effect = ProviderError("auth expired")

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result.success is False
    assert "auth expired" in result.message


def test_apply_move_fails_when_move_message_raises_provider_error():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="Label_7", name="Promotions")]
    provider.move_message.side_effect = ProviderError("rate limited")

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result.success is False
    assert "rate limited" in result.message


def test_apply_flag_delete_calls_delete_message():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="flag_delete", target_folder=None))

    assert result == ApplyResult(success=True, message="Movido para a Lixeira")
    provider.delete_message.assert_called_once_with("msg-1")


def test_apply_flag_delete_fails_when_delete_message_raises():
    provider = MagicMock()
    provider.delete_message.side_effect = ProviderError("not found")

    result = apply_proposal(provider, _proposal(action="flag_delete", target_folder=None))

    assert result.success is False
    assert "not found" in result.message


def test_apply_keep_is_a_noop():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="keep", target_folder=None))

    assert result.success is True
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def test_apply_error_action_is_a_noop():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="error", target_folder=None))

    assert result.success is True
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def test_apply_unknown_action_fails_without_calling_the_provider():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="archive", target_folder=None))

    assert result == ApplyResult(success=False, message="Ação desconhecida: archive")
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def _rule_proposal(**overrides) -> dict:
    fields = dict(
        action="create_rule", message_id="", target_folder="Promotions",
        rule_kind="sender", rule_value="news@shop.com", rule_match_count=3,
    )
    fields.update(overrides)
    return _proposal(**fields)


def _rule_provider(folders=None, rule_id="rule-1"):
    provider = MagicMock()
    provider.supports_rules.return_value = True
    provider.list_folders.return_value = folders or [Folder(id="Label_7", name="Promotions")]
    provider.create_rule.return_value = rule_id
    return provider


def test_create_rule_with_sender_condition_resolves_folder_and_returns_rule_id():
    provider = _rule_provider()

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is True
    assert result.rule_id == "rule-1"
    condition, folder_id = provider.create_rule.call_args.args
    assert condition.sender == "news@shop.com"
    assert condition.domain is None
    assert folder_id == "Label_7"
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def test_create_rule_with_domain_condition():
    provider = _rule_provider()

    result = apply_proposal(
        provider, _rule_proposal(rule_kind="domain", rule_value="shop.com")
    )

    assert result.success is True
    condition = provider.create_rule.call_args.args[0]
    assert condition.domain == "shop.com"
    assert condition.sender is None


def test_create_rule_fails_when_provider_does_not_support_rules():
    provider = _rule_provider()
    provider.supports_rules.return_value = False

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "suporta" in result.message
    provider.create_rule.assert_not_called()


def test_create_rule_fails_clearly_when_folder_no_longer_exists():
    provider = _rule_provider(folders=[Folder(id="INBOX", name="INBOX")])

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "Promotions" in result.message
    provider.create_rule.assert_not_called()


def test_create_rule_fails_when_list_folders_raises_provider_error():
    provider = _rule_provider()
    provider.list_folders.side_effect = ProviderError("auth expired")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "auth expired" in result.message


def test_create_rule_fails_when_provider_raises_provider_error():
    provider = _rule_provider()
    provider.create_rule.side_effect = ProviderError("quota exceeded")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False
    assert "quota exceeded" in result.message


def test_create_rule_fails_when_provider_raises_not_implemented():
    provider = _rule_provider()
    provider.create_rule.side_effect = NotImplementedError("no rules")

    result = apply_proposal(provider, _rule_proposal())

    assert result.success is False


def test_create_rule_fails_on_incomplete_proposal():
    provider = _rule_provider()

    result = apply_proposal(provider, _rule_proposal(rule_value=None))

    assert result.success is False
    provider.create_rule.assert_not_called()
