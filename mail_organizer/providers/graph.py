import functools
from datetime import datetime, timedelta, timezone

import requests

from mail_organizer.providers.base import EmailProvider, Folder, Message, RuleCondition
from mail_organizer.providers.errors import (
    MessageNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Graph omits internetMessageHeaders and the full body unless they are asked for.
MESSAGE_SELECT = (
    "id,parentFolderId,from,subject,receivedDateTime,bodyPreview,body,"
    "internetMessageHeaders"
)


def _map_http_error(exc: requests.HTTPError) -> ProviderError:
    status = getattr(getattr(exc, "response", None), "status_code", None)

    message = f"Microsoft Graph error: {exc}"
    if status in (401, 403):
        return ProviderAuthError(message)
    if status == 429:
        return ProviderRateLimitError(message)
    if status == 404:
        return MessageNotFoundError(message)
    return ProviderError(message)


def _translate_errors(func):
    """Translate requests errors into the provider error taxonomy."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as exc:
            raise _map_http_error(exc) from exc
        except requests.RequestException as exc:
            raise ProviderError(f"Microsoft Graph request failed: {exc}") from exc

    return wrapper


class GraphProvider(EmailProvider):
    def __init__(self, session):
        self._session = session

    @_translate_errors
    def list_folders(self) -> list[Folder]:
        response = self._session.get(f"{GRAPH_BASE}/me/mailFolders")
        response.raise_for_status()
        return [
            Folder(id=f["id"], name=f["displayName"])
            for f in response.json().get("value", [])
        ]

    @_translate_errors
    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        params = {"$select": MESSAGE_SELECT}
        if filters.get("days"):
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=filters["days"])
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"receivedDateTime ge {cutoff}"
        response = self._session.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder}/messages", params=params
        )
        response.raise_for_status()
        return [self._to_message(m) for m in response.json().get("value", [])]

    @_translate_errors
    def get_message(self, message_id: str) -> Message:
        response = self._session.get(
            f"{GRAPH_BASE}/me/messages/{message_id}",
            params={"$select": MESSAGE_SELECT},
        )
        response.raise_for_status()
        return self._to_message(response.json())

    def _to_message(self, data: dict) -> Message:
        body = data.get("body") or {}
        content_type = (body.get("contentType") or "").lower()
        content = body.get("content")
        return Message(
            id=data["id"],
            folder=data.get("parentFolderId", ""),
            sender=data.get("from", {})
            .get("emailAddress", {})
            .get("address", "")
            .lower(),
            subject=data.get("subject", ""),
            date=data.get("receivedDateTime", ""),
            snippet=data.get("bodyPreview", ""),
            body_text=content if content_type == "text" else None,
            body_html=content if content_type == "html" else None,
            headers={
                h["name"]: h["value"]
                for h in data.get("internetMessageHeaders") or []
            },
        )

    @_translate_errors
    def move_message(self, message_id: str, target_folder: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": target_folder},
        )
        response.raise_for_status()

    @_translate_errors
    def delete_message(self, message_id: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": "deleteditems"},
        )
        response.raise_for_status()

    def supports_rules(self) -> bool:
        return True

    @_translate_errors
    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        sender_contains = [condition.sender or f"@{condition.domain}"]
        body = {
            "displayName": f"mail-organizer-{condition.sender or condition.domain}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"senderContains": sender_contains},
            "actions": {
                "moveToFolder": target_folder,
                "stopProcessingRules": True,
            },
        }
        response = self._session.post(
            f"{GRAPH_BASE}/me/mailFolders/inbox/messageRules", json=body
        )
        response.raise_for_status()
        return response.json()["id"]
