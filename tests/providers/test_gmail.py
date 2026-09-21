import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.errors import (
    MessageNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from mail_organizer.providers.gmail import GmailProvider


def _mock_service():
    return MagicMock()


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _http_error(status: int) -> HttpError:
    resp = SimpleNamespace(status=status, reason="boom")
    return HttpError(resp, b'{"error": {"message": "boom"}}', uri="https://example")


def test_list_folders_returns_folders_with_ids_and_names():
    service = _mock_service()
    service.users().labels().list().execute.return_value = {
        "labels": [
            {"id": "INBOX", "name": "INBOX"},
            {"id": "Label_5", "name": "Promotions"},
        ]
    }
    provider = GmailProvider(service)

    result = provider.list_folders()

    assert [f.name for f in result] == ["INBOX", "Promotions"]
    assert [f.id for f in result] == ["INBOX", "Label_5"]


def test_list_messages_uses_newer_than_query_for_days_filter():
    service = _mock_service()
    service.users().messages().list().execute.return_value = {"messages": []}
    provider = GmailProvider(service)

    provider.list_messages("INBOX", {"days": 30})

    service.users().messages().list.assert_any_call(
        userId="me", labelIds=["INBOX"], q="newer_than:30d"
    )


def test_get_message_requests_full_format_and_returns_body_and_all_headers():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "snippet": "hello there",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": '"Foo Bar" <A@B.com>'},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "Thu, 01 Jan 2026 10:30:00 +0000"},
                {"name": "Message-Id", "value": "<abc@b.com>"},
                {"name": "List-Unsubscribe", "value": "<https://b.com/u>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Hello there")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>hello</p>")},
                },
            ],
        },
    }
    provider = GmailProvider(service)

    message = provider.get_message("msg-1")

    service.users().messages().get.assert_any_call(
        userId="me", id="msg-1", format="full"
    )
    assert message.id == "msg-1"
    assert message.body_text == "Hello there"
    assert message.body_html == "<p>hello</p>"
    assert message.snippet == "hello there"
    assert message.headers["Message-Id"] == "<abc@b.com>"
    assert message.headers["List-Unsubscribe"] == "<https://b.com/u>"
    assert len(message.headers) == 5


def test_get_message_normalizes_sender_and_date():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": '"Foo Bar" <A@B.com>'},
                {"name": "Date", "value": "Thu, 01 Jan 2026 10:30:00 +0000"},
            ]
        },
    }
    provider = GmailProvider(service)

    message = provider.get_message("msg-1")

    assert message.sender == "a@b.com"
    assert message.date == "2026-01-01T10:30:00+00:00"


def test_get_message_falls_back_to_raw_date_when_unparseable():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "payload": {"headers": [{"name": "Date", "value": "not a date"}]},
    }
    provider = GmailProvider(service)

    assert provider.get_message("msg-1").date == "not a date"


def test_get_message_decodes_unpadded_base64url_body():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [],
            "body": {"data": _b64("Olá").rstrip("=")},
        },
    }
    provider = GmailProvider(service)

    assert provider.get_message("msg-1").body_text == "Olá"


def test_move_message_removes_only_the_current_folder_label():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX", "UNREAD"],
    }
    provider = GmailProvider(service)

    provider.move_message("msg-1", "Promotions")

    service.users().messages().get.assert_any_call(
        userId="me", id="msg-1", format="minimal"
    )
    service.users().messages().modify.assert_any_call(
        userId="me",
        id="msg-1",
        body={"addLabelIds": ["Promotions"], "removeLabelIds": ["INBOX"]},
    )


def test_move_message_from_non_inbox_label_removes_that_label():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["Label_5", "IMPORTANT", "CATEGORY_PROMOTIONS"],
    }
    provider = GmailProvider(service)

    provider.move_message("msg-1", "Label_9")

    service.users().messages().modify.assert_any_call(
        userId="me",
        id="msg-1",
        body={"addLabelIds": ["Label_9"], "removeLabelIds": ["Label_5"]},
    )


def test_move_message_never_removes_the_label_it_adds():
    service = _mock_service()
    service.users().messages().get().execute.return_value = {
        "id": "msg-1",
        "labelIds": ["INBOX", "Promotions"],
    }
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


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitError),
        (404, MessageNotFoundError),
        (500, ProviderError),
    ],
)
def test_http_errors_are_translated_to_provider_errors(status, expected):
    service = _mock_service()
    service.users().messages().get().execute.side_effect = _http_error(status)
    provider = GmailProvider(service)

    with pytest.raises(expected):
        provider.get_message("msg-1")


def test_translated_error_does_not_leak_httperror():
    service = _mock_service()
    service.users().labels().list().execute.side_effect = _http_error(403)
    provider = GmailProvider(service)

    with pytest.raises(ProviderError) as excinfo:
        provider.list_folders()

    assert not isinstance(excinfo.value, HttpError)
