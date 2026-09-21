from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.gmail import GmailProvider


def _mock_service():
    return MagicMock()


def test_list_folders_returns_label_names():
    service = _mock_service()
    service.users().labels().list().execute.return_value = {
        "labels": [{"name": "INBOX"}, {"name": "Promotions"}]
    }
    provider = GmailProvider(service)

    assert provider.list_folders() == ["INBOX", "Promotions"]


def test_get_message_extracts_headers_and_snippet():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "snippet": "hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "2026-01-01"},
            ]
        },
    }
    provider = GmailProvider(service)

    message = provider.get_message("msg-1")

    assert message.id == "msg-1"
    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.snippet == "hello there"


def test_move_message_calls_modify_with_labels():
    service = _mock_service()
    provider = GmailProvider(service)

    provider.move_message("msg-1", "Promotions")

    service.users().messages().modify.assert_any_call(
        userId="me",
        id="msg-1",
        body={"addLabelIds": ["Promotions"], "removeLabelIds": ["INBOX"]},
    )


def test_delete_message_calls_trash():
    service = _mock_service()
    provider = GmailProvider(service)

    provider.delete_message("msg-1")

    service.users().messages().trash.assert_any_call(userId="me", id="msg-1")


def test_supports_rules_is_true():
    assert GmailProvider(_mock_service()).supports_rules() is True


def test_create_rule_with_sender_condition_calls_filters_create():
    service = _mock_service()
    service.users().settings().filters().create().execute.return_value = {
        "id": "filter-1"
    }
    provider = GmailProvider(service)

    rule_id = provider.create_rule(RuleCondition(sender="a@b.com"), "Promotions")

    assert rule_id == "filter-1"
    service.users().settings().filters().create.assert_any_call(
        userId="me",
        body={
            "criteria": {"from": "a@b.com"},
            "action": {"addLabelIds": ["Promotions"]},
        },
    )


def test_create_rule_with_domain_condition_uses_wildcard():
    service = _mock_service()
    service.users().settings().filters().create().execute.return_value = {
        "id": "filter-2"
    }
    provider = GmailProvider(service)

    provider.create_rule(RuleCondition(domain="newsletter.com"), "Promotions")

    service.users().settings().filters().create.assert_any_call(
        userId="me",
        body={
            "criteria": {"from": "*@newsletter.com"},
            "action": {"addLabelIds": ["Promotions"]},
        },
    )
