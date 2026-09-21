class ProviderError(Exception):
    """Base exception for all EmailProvider errors."""


class ProviderAuthError(ProviderError):
    """Authentication/authorization failed against the provider."""


class ProviderRateLimitError(ProviderError):
    """The provider rate-limited this request."""


class MessageNotFoundError(ProviderError):
    """The requested message no longer exists."""
