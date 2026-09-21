import re
from dataclasses import dataclass


@dataclass
class AuthResult:
    spf: str | None = None
    dkim: str | None = None
    dmarc: str | None = None


def _get_header(headers: dict, name: str) -> str | None:
    lower_name = name.lower()
    for key, value in headers.items():
        if key.lower() == lower_name:
            return value
    return None


def parse_authentication_results(headers: dict) -> AuthResult:
    raw = _get_header(headers, "Authentication-Results")
    if not raw:
        return AuthResult()

    def _extract(mechanism: str) -> str | None:
        match = re.search(rf"{mechanism}=(\w+)", raw, re.IGNORECASE)
        return match.group(1).lower() if match else None

    return AuthResult(
        spf=_extract("spf"),
        dkim=_extract("dkim"),
        dmarc=_extract("dmarc"),
    )
