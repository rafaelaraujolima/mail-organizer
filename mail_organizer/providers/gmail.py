from mail_organizer.providers.base import EmailProvider, Message, RuleCondition


class GmailProvider(EmailProvider):
    def __init__(self, service):
        self._service = service

    def list_folders(self) -> list[str]:
        result = self._service.users().labels().list(userId="me").execute()
        return [label["name"] for label in result.get("labels", [])]

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

    def get_message(self, message_id: str) -> Message:
        raw = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = {
            h["name"]: h["value"] for h in raw.get("payload", {}).get("headers", [])
        }
        return Message(
            id=raw["id"],
            folder=",".join(raw.get("labelIds", [])),
            sender=headers.get("From", ""),
            subject=headers.get("Subject", ""),
            date=headers.get("Date", ""),
            snippet=raw.get("snippet", ""),
            headers=headers,
        )

    def move_message(self, message_id: str, target_folder: str) -> None:
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [target_folder], "removeLabelIds": ["INBOX"]},
        ).execute()

    def delete_message(self, message_id: str) -> None:
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def supports_rules(self) -> bool:
        return True

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
