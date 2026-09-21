from typing import Callable

from mail_organizer.db import Database
from mail_organizer.providers.base import EmailProvider

ProviderFactory = Callable[[dict], EmailProvider]


class AccountService:
    def __init__(self, db: Database, provider_factories: dict[str, ProviderFactory]):
        self._db = db
        self._provider_factories = provider_factories

    def connect_account(
        self, account_id: str, provider: str, display_name: str, credentials: dict
    ) -> None:
        self._db.save_account(account_id, provider, display_name, credentials)

    def list_accounts(self) -> list[dict]:
        return self._db.list_accounts()

    def get_provider(self, account_id: str) -> EmailProvider:
        account = self._db.get_account(account_id)
        if account is None:
            raise LookupError(f"Unknown account: {account_id}")

        factory = self._provider_factories.get(account["provider"])
        if factory is None:
            raise ValueError(f"No provider factory registered for: {account['provider']}")

        return factory(account["credentials"])
