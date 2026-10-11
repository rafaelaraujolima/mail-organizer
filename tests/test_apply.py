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
