import base64
import functools
from email.utils import parseaddr, parsedate_to_datetime

from googleapiclient.errors import HttpError

from mail_organizer.providers.base import EmailProvider, Folder, Message, RuleCondition
from mail_organizer.providers.errors import (
    MessageNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

# Labels that describe a message's state rather than where it is filed, and so
# must survive a move.
STATE_LABELS = frozenset({"UNREAD", "STARRED", "IMPORTANT"})


def _map_http_error(exc: HttpError) -> ProviderError:
    try:
        status = int(exc.resp.status)
    except (AttributeError, TypeError, ValueError):
        status = None

    message = f"Gmail API error: {exc}"
    if status in (401, 403):
        return ProviderAuthError(message)
    if status == 429:
        return ProviderRateLimitError(message)
    if status == 404:
        return MessageNotFoundError(message)
    return ProviderError(message)


def _translate_errors(func):
    """Translate googleapiclient errors into the provider error taxonomy."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            raise _map_http_error(exc) from exc

    return wrapper


class GmailProvider(EmailProvider):
    def __init__(self, service):
        self._service = service

    @_translate_errors
    def list_folders(self) -> list[Folder]:
        result = self._service.users().labels().list(userId="me").execute()
        return [
            Folder(id=label["id"], name=label["name"])
            for label in result.get("labels", [])
        ]

    @_translate_errors
    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        query_parts = []
        if filters.get("days"):
            query_parts.append(f"newer_than:{filters['days']}d")
        list_kwargs = {"userId": "me"}
        if folder:
            list_kwargs["labelIds"] = [folder]
        if query_parts:
            list_kwargs["q"] = " ".join(query_parts)

        result = self._service.users().messages().list(**list_kwargs).execute()
        return [self.get_message(item["id"]) for item in result.get("messages", [])]

    @_translate_errors
    def get_message(self, message_id: str) -> Message:
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = raw.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        return Message(
            id=raw["id"],
            folder=",".join(raw.get("labelIds", [])),
            sender=parseaddr(headers.get("From", ""))[1].lower(),
            subject=headers.get("Subject", ""),
            date=self._normalize_date(headers.get("Date", "")),
            snippet=raw.get("snippet", ""),
            body_text=self._find_body(payload, "text/plain"),
            body_html=self._find_body(payload, "text/html"),
            headers=headers,
        )

    @staticmethod
    def _normalize_date(raw_date: str) -> str:
        if not raw_date:
            return ""
        try:
            return parsedate_to_datetime(raw_date).isoformat()
        except (TypeError, ValueError):
            return raw_date

    @staticmethod
    def _decode_body_data(data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

    @classmethod
    def _find_body(cls, payload: dict, mime_type: str) -> str | None:
        """Return the first body part of ``mime_type``, searching parts recursively."""
        if payload.get("mimeType") == mime_type:
            data = payload.get("body", {}).get("data")
            if data:
                return cls._decode_body_data(data)
        for part in payload.get("parts", []):
            found = cls._find_body(part, mime_type)
            if found is not None:
                return found
        return None

    @_translate_errors
    def move_message(self, message_id: str, target_folder: str) -> None:
        current = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="minimal")
            .execute()
        )
        remove_label_ids = [
            label_id
            for label_id in current.get("labelIds", [])
            # The label being added is never also removed: a message already
            # filed under target_folder would otherwise appear in both lists.
            if label_id != target_folder
            and label_id not in STATE_LABELS
            and not label_id.startswith("CATEGORY_")
        ]
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={
                "addLabelIds": [target_folder],
                "removeLabelIds": remove_label_ids,
            },
        ).execute()

    @_translate_errors
    def delete_message(self, message_id: str) -> None:
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def supports_rules(self) -> bool:
        return True

    @_translate_errors
    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        sender_pattern = condition.sender or f"*@{condition.domain}"
        body = {
            "criteria": {"from": sender_pattern},
            "action": {"addLabelIds": [target_folder]},
        }
        result = (
            self._service.users()
            .settings()
            .filters()
            .create(userId="me", body=body)
            .execute()
        )
        return result["id"]
