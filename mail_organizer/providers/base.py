from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    folder: str
    sender: str
    subject: str
    date: str
    snippet: str = ""
    body_text: str | None = None
    body_html: str | None = None
    headers: dict = field(default_factory=dict)


@dataclass
class RuleCondition:
    sender: str | None = None
    domain: str | None = None

    def __post_init__(self):
        if not self.sender and not self.domain:
            raise ValueError("RuleCondition requires sender or domain")
        if self.sender and self.domain:
            raise ValueError("RuleCondition accepts only one of sender or domain")


class EmailProvider(ABC):
    @abstractmethod
    def list_folders(self) -> list[str]:
        ...

    @abstractmethod
    def list_messages(self, folder: str, filters: dict) -> list[Message]:
        ...

    @abstractmethod
    def get_message(self, message_id: str) -> Message:
        ...

    @abstractmethod
    def move_message(self, message_id: str, target_folder: str) -> None:
        ...

    @abstractmethod
    def delete_message(self, message_id: str) -> None:
        ...

    def supports_rules(self) -> bool:
        return False

    def create_rule(self, condition: RuleCondition, target_folder: str) -> str:
        raise NotImplementedError(
            f"{type(self).__name__} does not support rule creation"
        )
