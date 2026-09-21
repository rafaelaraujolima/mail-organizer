from unittest.mock import MagicMock

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.graph import GRAPH_BASE, GraphProvider


def _mock_response(json_body):
    response = MagicMock()
    response.json.return_value = json_body
    response.raise_for_status.return_value = None
    return response


def test_list_folders_returns_display_names():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {"value": [{"displayName": "Inbox"}, {"displayName": "Promotions"}]}
    )
    provider = GraphProvider(session)

    assert provider.list_folders() == ["Inbox", "Promotions"]
    session.get.assert_called_with(f"{GRAPH_BASE}/me/mailFolders")


def test_get_message_maps_fields():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {
            "id": "msg-1",
            "parentFolderId": "inbox-id",
            "from": {"emailAddress": {"address": "a@b.com"}},
            "subject": "Hi",
            "receivedDateTime": "2026-01-01T00:00:00Z",
            "bodyPreview": "hello there",
            "body": {"content": "<p>hello</p>"},
        }
    )
    provider = GraphProvider(session)

    message = provider.get_message("msg-1")

    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.body_html == "<p>hello</p>"


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
