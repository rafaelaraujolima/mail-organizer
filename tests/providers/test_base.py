import pytest

from mail_organizer.providers.base import (
    EmailProvider,
    Folder,
    Message,
    RuleCondition,
)


def test_rule_condition_requires_sender_or_domain():
    with pytest.raises(ValueError):
        RuleCondition()


def test_rule_condition_rejects_both_sender_and_domain():
    with pytest.raises(ValueError):
        RuleCondition(sender="a@b.com", domain="b.com")


def test_rule_condition_accepts_sender_only():
    condition = RuleCondition(sender="a@b.com")
    assert condition.sender == "a@b.com"
    assert condition.domain is None


def test_folder_carries_id_name_and_defaults_flags_to_empty():
    folder = Folder(id="Label_5", name="Promotions")

    assert folder.id == "Label_5"
    assert folder.name == "Promotions"
    assert folder.flags == ()


def test_folder_accepts_flags():
    folder = Folder(id="Deleted Messages", name="Deleted Messages", flags=(b"\\Trash",))

    assert folder.flags == (b"\\Trash",)


def test_message_defaults():
    message = Message(
        id="1", folder="INBOX", sender="a@b.com", subject="hi", date="2026-01-01"
    )
    assert message.snippet == ""
    assert message.body_text is None
    assert message.headers == {}


class _MinimalProvider(EmailProvider):
    def list_folders(self):
        return []

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


def test_supports_rules_defaults_to_false():
    assert _MinimalProvider().supports_rules() is False


def test_create_rule_raises_not_implemented_by_default():
    provider = _MinimalProvider()
    with pytest.raises(NotImplementedError):
        provider.create_rule(RuleCondition(domain="b.com"), "Promotions")


def test_email_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        EmailProvider()
