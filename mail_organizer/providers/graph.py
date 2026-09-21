from mail_organizer.providers.base import EmailProvider, Message, RuleCondition

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphProvider(EmailProvider):
    def __init__(self, session):
        self._session = session

    def list_folders(self) -> list[str]:
        response = self._session.get(f"{GRAPH_BASE}/me/mailFolders")
        response.raise_for_status()
        return [f["displayName"] for f in response.json().get("value", [])]

    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        params = {}
        if filters.get("days"):
            params["$filter"] = f"receivedDateTime ge {filters['days']}"
        response = self._session.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder}/messages", params=params
        )
        response.raise_for_status()
        return [self._to_message(m) for m in response.json().get("value", [])]

    def get_message(self, message_id: str) -> Message:
        response = self._session.get(f"{GRAPH_BASE}/me/messages/{message_id}")
        response.raise_for_status()
        return self._to_message(response.json())

    def _to_message(self, data: dict) -> Message:
        return Message(
            id=data["id"],
            folder=data.get("parentFolderId", ""),
            sender=data.get("from", {}).get("emailAddress", {}).get("address", ""),
            subject=data.get("subject", ""),
            date=data.get("receivedDateTime", ""),
            snippet=data.get("bodyPreview", ""),
            body_html=data.get("body", {}).get("content"),
        )

    def move_message(self, message_id: str, target_folder: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": target_folder},
        )
        response.raise_for_status()

    def delete_message(self, message_id: str) -> None:
        response = self._session.post(
            f"{GRAPH_BASE}/me/messages/{message_id}/move",
            json={"destinationId": "deleteditems"},
        )
        response.raise_for_status()

    def supports_rules(self) -> bool:
        return True

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
