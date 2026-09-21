import imaplib
from collections import namedtuple
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from imapclient.exceptions import IMAPClientError, LoginError

from mail_organizer.providers.base import RuleCondition
from mail_organizer.providers.errors import ProviderAuthError, ProviderError
from mail_organizer.providers.imap import ImapProvider

# Mirrors imapclient's Address namedtuple shape: (name, route, mailbox, host),
# where mailbox/host are raw bytes as returned by a real IMAP server.
Address = namedtuple("Address", ["name", "route", "mailbox", "host"])

RAW_EMAIL = (
    b"From: a@b.com\r\n"
    b"Subject: Hi\r\n"
    b"Message-Id: <abc@b.com>\r\n"
    b"List-Unsubscribe: <https://b.com/u>\r\n"
    b"Content-Type: text/plain\r\n"
    b"\r\n"
    b"Hello there"
)


def _envelope(subject=b"Hi", date=datetime(2026, 1, 1, 10, 30)):
    envelope = MagicMock()
    envelope.from_ = [Address(name=None, route=None, mailbox=b"A", host=b"B.com")]
    envelope.subject = subject
    envelope.date = date
    return envelope


def _selected_provider(client, folder="INBOX"):
    """Return a provider that has selected ``folder`` via list_messages()."""
    client.search.return_value = []
    provider = ImapProvider(client)
    provider.list_messages(folder, {})
    return provider


def _fetch_result(envelope=None, raw_email=RAW_EMAIL, uid=42):
    return {uid: {b"ENVELOPE": envelope or _envelope(), b"RFC822": raw_email}}


def test_list_folders_returns_folders_with_names_ids_and_flags():
    client = MagicMock()
    client.list_folders.return_value = [
        ((b"\\HasNoChildren",), b"/", "INBOX"),
        ((b"\\HasNoChildren", b"\\Trash"), b"/", "Deleted Messages"),
    ]
    provider = ImapProvider(client)

    result = provider.list_folders()

    assert [f.name for f in result] == ["INBOX", "Deleted Messages"]
    assert [f.id for f in result] == ["INBOX", "Deleted Messages"]
    assert result[1].flags == (b"\\HasNoChildren", b"\\Trash")


def test_list_messages_selects_folder_for_writing():
    client = MagicMock()
    client.search.return_value = []
    provider = ImapProvider(client)

    provider.list_messages("Archive", {})

    client.select_folder.assert_called_once_with("Archive", readonly=False)
    client.search.assert_called_once_with(["ALL"])


def test_list_messages_days_filter_searches_since_cutoff_date():
    client = MagicMock()
    client.search.return_value = []
    provider = ImapProvider(client)

    provider.list_messages("INBOX", {"days": 7})

    expected_date = (datetime.now() - timedelta(days=7)).date()
    client.search.assert_called_once_with(["SINCE", expected_date])


def test_get_message_parses_envelope_body_headers_and_folder():
    client = MagicMock()
    client.fetch.return_value = _fetch_result()
    provider = _selected_provider(client, folder="Archive")

    message = provider.get_message("42")

    assert message.id == "42"
    assert message.folder == "Archive"
    assert message.sender == "a@b.com"
    assert message.subject == "Hi"
    assert message.date == "2026-01-01T10:30:00"
    assert message.body_text == "Hello there"
    assert message.headers["Message-Id"] == "<abc@b.com>"
    assert message.headers["List-Unsubscribe"] == "<https://b.com/u>"
    assert message.headers["From"] == "a@b.com"
    assert len(message.headers) == 5


def test_get_message_falls_back_to_str_for_non_datetime_date():
    client = MagicMock()
    client.fetch.return_value = _fetch_result(envelope=_envelope(date=None))
    provider = _selected_provider(client)

    assert provider.get_message("42").date == "None"


def test_get_message_decodes_rfc2047_encoded_subject():
    client = MagicMock()
    client.fetch.return_value = _fetch_result(
        envelope=_envelope(subject=b"=?UTF-8?Q?Ol=C3=A1?=")
    )
    provider = _selected_provider(client)

    assert provider.get_message("42").subject == "Olá"


def test_get_message_decodes_raw_utf8_subject():
    client = MagicMock()
    client.fetch.return_value = _fetch_result(
        envelope=_envelope(subject="Olá".encode("utf-8"))
    )
    provider = _selected_provider(client)

    assert provider.get_message("42").subject == "Olá"


def test_get_message_falls_back_to_latin1_for_non_utf8_subject():
    client = MagicMock()
    client.fetch.return_value = _fetch_result(
        envelope=_envelope(subject="Olá".encode("latin-1"))
    )
    provider = _selected_provider(client)

    assert provider.get_message("42").subject == "Olá"


def test_get_message_decodes_body_using_declared_charset():
    client = MagicMock()
    raw_email = (
        b'Content-Type: text/plain; charset="iso-8859-1"\r\n'
        b"\r\n" + "Olá senhor".encode("latin-1")
    )
    client.fetch.return_value = _fetch_result(raw_email=raw_email)
    provider = _selected_provider(client)

    assert provider.get_message("42").body_text == "Olá senhor"


def test_get_message_extracts_html_part_from_multipart():
    client = MagicMock()
    raw_email = (
        b"Content-Type: multipart/alternative; boundary=BOUND\r\n"
        b"\r\n"
        b"--BOUND\r\n"
        b"Content-Type: text/plain\r\n\r\nHello there\r\n"
        b"--BOUND\r\n"
        b"Content-Type: text/html\r\n\r\n<p>hello</p>\r\n"
        b"--BOUND--\r\n"
    )
    client.fetch.return_value = _fetch_result(raw_email=raw_email)
    provider = _selected_provider(client)

    message = provider.get_message("42")

    assert message.body_text == "Hello there"
    assert message.body_html == "<p>hello</p>"


def test_move_message_calls_client_move():
    client = MagicMock()
    provider = _selected_provider(client)

    provider.move_message("42", "Promotions")

    client.move.assert_called_with([42], "Promotions")


def test_delete_message_moves_to_folder_flagged_as_trash():
    client = MagicMock()
    client.list_folders.return_value = [
        ((b"\\HasNoChildren",), b"/", "INBOX"),
        ((b"\\Trash",), b"/", "Deleted Messages"),
    ]
    provider = _selected_provider(client)

    provider.delete_message("42")

    client.move.assert_called_with([42], "Deleted Messages")


def test_delete_message_falls_back_to_trash_when_no_folder_is_flagged():
    client = MagicMock()
    client.list_folders.return_value = [
        ((b"\\HasNoChildren",), b"/", "INBOX"),
        ((), b"/", "Promotions"),
    ]
    provider = _selected_provider(client)

    provider.delete_message("42")

    client.move.assert_called_with([42], "Trash")


@pytest.mark.parametrize(
    "call",
    [
        lambda p: p.get_message("42"),
        lambda p: p.move_message("42", "Promotions"),
        lambda p: p.delete_message("42"),
    ],
)
def test_operations_require_a_selected_folder(call):
    client = MagicMock()
    provider = ImapProvider(client)

    with pytest.raises(ProviderError, match="No folder selected"):
        call(provider)

    client.fetch.assert_not_called()
    client.move.assert_not_called()


def test_login_errors_are_translated_to_provider_auth_error():
    client = MagicMock()
    client.list_folders.side_effect = LoginError("bad credentials")
    provider = ImapProvider(client)

    with pytest.raises(ProviderAuthError):
        provider.list_folders()


def test_imap_protocol_errors_are_translated_to_provider_error():
    client = MagicMock()
    client.search.return_value = []
    provider = ImapProvider(client)
    provider.list_messages("INBOX", {})
    client.fetch.side_effect = IMAPClientError("command failed")

    with pytest.raises(ProviderError) as excinfo:
        provider.get_message("42")

    assert not isinstance(excinfo.value, imaplib.IMAP4.error)


def test_connection_errors_are_translated_to_provider_error():
    client = MagicMock()
    client.select_folder.side_effect = OSError("connection reset")
    provider = ImapProvider(client)

    with pytest.raises(ProviderError):
        provider.list_messages("INBOX", {})


def test_supports_rules_is_false():
    assert ImapProvider(MagicMock()).supports_rules() is False


def test_create_rule_raises_not_implemented():
    provider = ImapProvider(MagicMock())

    with pytest.raises(NotImplementedError):
        provider.create_rule(RuleCondition(domain="b.com"), "Promotions")
