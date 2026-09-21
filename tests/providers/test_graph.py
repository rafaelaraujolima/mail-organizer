from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import requests

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.errors import (
    MessageNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from mail_organizer.providers.graph import GRAPH_BASE, MESSAGE_SELECT, GraphProvider

FILTER_PREFIX = "receivedDateTime ge "


def _mock_response(json_body):
    response = MagicMock()
    response.json.return_value = json_body
    response.raise_for_status.return_value = None
    return response


def _failing_response(status):
    response = MagicMock()
    error = requests.HTTPError("boom", response=MagicMock(status_code=status))
    response.raise_for_status.side_effect = error
    return response


def test_list_folders_returns_folders_with_ids_and_names():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "value": [
                {"id": "inbox-id", "displayName": "Inbox"},
                {"id": "promo-id", "displayName": "Promotions"},
            ]
        }
    )
    provider = GraphProvider(session)

    result = provider.list_folders()

    assert [f.name for f in result] == ["Inbox", "Promotions"]
    assert [f.id for f in result] == ["inbox-id", "promo-id"]
    session.get.assert_called_with(f"{GRAPH_BASE}/me/mailFolders")


def test_get_message_selects_headers_and_body_and_maps_fields():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "id": "msg-1",
            "parentFolderId": "inbox-id",
            "from": {"emailAddress": {"address": "A@B.com"}},
            "subject": "Hi",
            "receivedDateTime": "2026-01-01T00:00:00Z",
            "bodyPreview": "hello there",
            "body": {"contentType": "html", "content": "<p>hello</p>"},
            "internetMessageHeaders": [
                {"name": "Message-Id", "value": "<abc@b.com>"},
                {"name": "List-Unsubscribe", "value": "<https://b.com/u>"},
                {"name": "X-Spam-Score", "value": "0.1"},
                {"name": "Received", "value": "by mx.b.com"},
            ],
        }
    )
    provider = GraphProvider(session)

    message = provider.get_message("msg-1")

    session.get.assert_called_with(
        f"{GRAPH_BASE}/me/messages/msg-1", params={"$select": MESSAGE_SELECT}
    )
    assert "internetMessageHeaders" in MESSAGE_SELECT
    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.folder == "inbox-id"
    assert message.date == "2026-01-01T00:00:00Z"
    assert message.body_html == "<p>hello</p>"
    assert message.body_text is None
    assert message.headers["Message-Id"] == "<abc@b.com>"
    assert message.headers["X-Spam-Score"] == "0.1"
    assert len(message.headers) == 4


def test_get_message_maps_text_body_to_body_text():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "id": "msg-1",
            "body": {"contentType": "text", "content": "Hello there"},
        }
    )
    provider = GraphProvider(session)

    message = provider.get_message("msg-1")

    assert message.body_text == "Hello there"
    assert message.body_html is None


def test_list_messages_without_filters_selects_fields_and_omits_filter():
    session = MagicMock()
    session.get.return_value = _mock_response({"value": []})
    provider = GraphProvider(session)

    provider.list_messages("inbox-id", {})

    session.get.assert_called_with(
        f"{GRAPH_BASE}/me/mailFolders/inbox-id/messages",
        params={"$select": MESSAGE_SELECT},
    )


def test_list_messages_days_filter_uses_iso_datetime_cutoff():
    session = MagicMock()
    session.get.return_value = _mock_response({"value": []})
    provider = GraphProvider(session)

    provider.list_messages("inbox-id", {"days": 30})

    params = session.get.call_args.kwargs["params"]
    assert params["$filter"].startswith(FILTER_PREFIX)
    cutoff = datetime.strptime(
        params["$filter"][len(FILTER_PREFIX) :], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    expected = datetime.now(timezone.utc) - timedelta(days=30)
    assert abs((cutoff - expected).total_seconds()) < 60


def test_move_message_posts_destination_id():
    session = MagicMock()
    session.post.return_value = _mock_response({})
    provider = GraphProvider(session)

    provider.move_message("msg-1", "promotions-id")

    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/messages/msg-1/move",
        json={"destinationId": "promotions-id"},
    )


def test_delete_message_moves_to_deleted_items():
    session = MagicMock()
    session.post.return_value = _mock_response({})
    provider = GraphProvider(session)

    provider.delete_message("msg-1")

    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/messages/msg-1/move",
        json={"destinationId": "deleteditems"},
    )


def test_supports_rules_is_true():
    assert GraphProvider(MagicMock()).supports_rules() is True


def test_create_rule_posts_message_rule():
    session = MagicMock()
    session.post.return_value = _mock_response({"id": "rule-1"})
    provider = GraphProvider(session)

    rule_id = provider.create_rule(RuleCondition(domain="newsletter.com"), "promotions-id")

    assert rule_id == "rule-1"
    session.post.assert_called_with(
        f"{GRAPH_BASE}/me/mailFolders/inbox/messageRules",
        json={
            "displayName": "mail-organizer-newsletter.com",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"senderContains": ["@newsletter.com"]},
            "actions": {"moveToFolder": "promotions-id", "stopProcessingRules": True},
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
    session = MagicMock()
    session.get.return_value = _failing_response(status)
    provider = GraphProvider(session)

    with pytest.raises(expected):
        provider.get_message("msg-1")


def test_connection_errors_are_translated_to_provider_error():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("no route to host")
    provider = GraphProvider(session)

    with pytest.raises(ProviderError) as excinfo:
        provider.move_message("msg-1", "promotions-id")

    assert not isinstance(excinfo.value, requests.RequestException)
