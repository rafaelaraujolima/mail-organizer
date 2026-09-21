from collections import namedtuple
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.imap import ImapProvider

# Mirrors imapclient's Address namedtuple shape: (name, route, mailbox, host),
# where mailbox/host are raw bytes as returned by a real IMAP server.
Address = namedtuple("Address", ["name", "route", "mailbox", "host"])


def test_list_folders_returns_folder_names():
    client = MagicMock()
    client.list_folders.return_value = [
        ((), b"/", "INBOX"),
        ((), b"/", "Promotions"),
    ]
    provider = ImapProvider(client)

    assert provider.list_folders() == ["INBOX", "Promotions"]


def test_get_message_parses_envelope_and_body():
    client = MagicMock()
    envelope = MagicMock()
    envelope.from_ = [Address(name=None, route=None, mailbox=b"a", host=b"b.com")]
    envelope.subject = b"Hi"
    envelope.date = "2026-01-01"
    raw_email = (
        b"Content-Type: text/plain\r\n\r\nHello there"
    )
    client.fetch.return_value = {
        42: {b"ENVELOPE": envelope, b"RFC822": raw_email}
    }
    provider = ImapProvider(client)

    message = provider.get_message("42")

    assert message.id == "42"
    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.body_text == "Hello there"


def test_get_message_decodes_rfc2047_encoded_subject():
    client = MagicMock()
    envelope = MagicMock()
    envelope.from_ = [Address(name=None, route=None, mailbox=b"a", host=b"b.com")]
    envelope.subject = b"=?UTF-8?Q?Ol=C3=A1?="
    envelope.date = "2026-01-01"
    raw_email = b"Content-Type: text/plain\r\n\r\nHello there"
    client.fetch.return_value = {
        42: {b"ENVELOPE": envelope, b"RFC822": raw_email}
    }
    provider = ImapProvider(client)

    message = provider.get_message("42")

    assert message.subject == "Olá"


def test_move_message_calls_client_move():
    client = MagicMock()
    provider = ImapProvider(client)

    provider.move_message("42", "Promotions")

    client.move.assert_called_with([42], "Promotions")


def test_delete_message_moves_to_trash():
    client = MagicMock()
    provider = ImapProvider(client)

    provider.delete_message("42")

    client.move.assert_called_with([42], "Trash")


def test_supports_rules_is_false():
    assert ImapProvider(MagicMock()).supports_rules() is False


def test_create_rule_raises_not_implemented():
    provider = ImapProvider(MagicMock())

    with pytest.raises(NotImplementedError):
        from mail_organizer.providers.base import RuleCondition

        provider.create_rule(RuleCondition(domain="b.com"), "Promotions")
