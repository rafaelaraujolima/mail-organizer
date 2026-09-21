import email
from email.header import decode_header
from email.message import Message as EmailMessage

from mail_organizer.providers.base import EmailProvider, Message


class ImapProvider(EmailProvider):
    def __init__(self, client):
        self._client = client

    def list_folders(self) -> list[str]:
        return [name for _, _, name in self._client.list_folders()]

    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        self._client.select_folder(folder, readonly=True)
        search_criteria = ["ALL"]
        message_ids = self._client.search(search_criteria)
        return [self.get_message(str(msg_id)) for msg_id in message_ids]

    def get_message(self, message_id: str) -> Message:
        data = self._client.fetch([int(message_id)], ["ENVELOPE", "RFC822"])
        entry = data[int(message_id)]
        envelope = entry[b"ENVELOPE"]
        parsed = email.message_from_bytes(entry[b"RFC822"])

        return Message(
            id=message_id,
            folder="",
            sender=self._format_address(envelope.from_[0]) if envelope.from_ else "",
            subject=self._decode_subject(envelope.subject),
            date=str(envelope.date),
            body_text=self._extract_part(parsed, "text/plain"),
            body_html=self._extract_part(parsed, "text/html"),
        )

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
        decoded_parts = decode_header(subject.decode("ascii", errors="replace"))
        return "".join(
            part.decode(encoding or "utf-8", errors="replace")
            if isinstance(part, bytes)
            else part
            for part, encoding in decoded_parts
        )

    @staticmethod
    def _extract_part(parsed: EmailMessage, content_type: str) -> str | None:
        if parsed.get_content_type() == content_type:
            return parsed.get_payload(decode=True).decode(errors="replace")
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == content_type:
                    return part.get_payload(decode=True).decode(errors="replace")
        return None

    def move_message(self, message_id: str, target_folder: str) -> None:
        self._client.move([int(message_id)], target_folder)

    def delete_message(self, message_id: str) -> None:
        self._client.move([int(message_id)], "Trash")
