import email
import functools
import imaplib
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message as EmailMessage

from imapclient.exceptions import LoginError

from mail_organizer.providers.base import EmailProvider, Folder, Message
from mail_organizer.providers.errors import ProviderAuthError, ProviderError

DEFAULT_TRASH_FOLDER = "Trash"
TRASH_FLAG = "\\trash"


def _translate_errors(func):
    """Translate imapclient/socket errors into the provider error taxonomy."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except LoginError as exc:
            raise ProviderAuthError(f"IMAP authentication failed: {exc}") from exc
        except imaplib.IMAP4.error as exc:
            raise ProviderError(f"IMAP error: {exc}") from exc
        except OSError as exc:
            raise ProviderError(f"IMAP connection error: {exc}") from exc

    return wrapper


class ImapProvider(EmailProvider):
    def __init__(self, client):
        self._client = client
        self._selected_folder: str | None = None

    @_translate_errors
    def list_folders(self) -> list[Folder]:
        return [
            Folder(id=name, name=name, flags=tuple(flags))
            for flags, _, name in self._client.list_folders()
        ]

    @_translate_errors
    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        self._client.select_folder(folder, readonly=False)
        self._selected_folder = folder

        if filters.get("days"):
            cutoff_date = (datetime.now() - timedelta(days=filters["days"])).date()
            search_criteria = ["SINCE", cutoff_date]
        else:
            search_criteria = ["ALL"]

        message_ids = self._client.search(search_criteria)
        return [self.get_message(str(msg_id)) for msg_id in message_ids]

    def _require_selected_folder(self) -> str:
        if self._selected_folder is None:
            raise ProviderError("No folder selected — call list_messages first")
        return self._selected_folder

    @_translate_errors
    def get_message(self, message_id: str) -> Message:
        folder = self._require_selected_folder()
        data = self._client.fetch([int(message_id)], ["ENVELOPE", "RFC822"])
        entry = data[int(message_id)]
        envelope = entry[b"ENVELOPE"]
        parsed = email.message_from_bytes(entry[b"RFC822"])

        return Message(
            id=message_id,
            folder=folder,
            sender=(
                self._format_address(envelope.from_[0]).lower()
                if envelope.from_
                else ""
            ),
            subject=self._decode_subject(envelope.subject),
            date=self._normalize_date(envelope.date),
            body_text=self._extract_part(parsed, "text/plain"),
            body_html=self._extract_part(parsed, "text/html"),
            headers=dict(parsed.items()),
        )

    @staticmethod
    def _normalize_date(value) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _format_address(addr) -> str:
        if addr is None:
            return ""
        mailbox = addr.mailbox.decode() if addr.mailbox else ""
        host = addr.host.decode() if addr.host else ""
        if mailbox and host:
            return f"{mailbox}@{host}"
        return mailbox or host

    @staticmethod
    def _decode_subject(subject: bytes | None) -> str:
        if not subject:
            return ""
        if isinstance(subject, bytes):
            try:
                raw = subject.decode("utf-8")
            except UnicodeDecodeError:
                raw = subject.decode("latin-1")
        else:
            raw = subject
        decoded_parts = decode_header(raw)
        return "".join(
            part.decode(encoding or "utf-8", errors="replace")
            if isinstance(part, bytes)
            else part
            for part, encoding in decoded_parts
        )

    @staticmethod
    def _decode_payload(part: EmailMessage) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            # Servers do send charsets Python has never heard of.
            return payload.decode("utf-8", errors="replace")

    @classmethod
    def _extract_part(cls, parsed: EmailMessage, content_type: str) -> str | None:
        if parsed.get_content_type() == content_type:
            return cls._decode_payload(parsed)
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == content_type:
                    return cls._decode_payload(part)
        return None

    @_translate_errors
    def move_message(self, message_id: str, target_folder: str) -> None:
        self._require_selected_folder()
        self._client.move([int(message_id)], target_folder)

    @_translate_errors
    def delete_message(self, message_id: str) -> None:
        self._require_selected_folder()
        self._client.move([int(message_id)], self._resolve_trash_folder())

    def _resolve_trash_folder(self) -> str:
        """Find the mailbox the server advertises with the \\Trash special-use flag."""
        for folder in self.list_folders():
            for flag in folder.flags:
                text = (
                    flag.decode("ascii", errors="replace")
                    if isinstance(flag, bytes)
                    else str(flag)
                )
                if text.lower() == TRASH_FLAG:
                    return folder.id
        return DEFAULT_TRASH_FOLDER
