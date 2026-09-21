import re
from dataclasses import dataclass
from email.utils import parseaddr


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


def _extract_domain(address: str) -> str | None:
    if not address or "@" not in address:
        return None
    return address.rsplit("@", 1)[-1].lower()


def detect_domain_mismatch(sender: str, headers: dict) -> bool:
    return_path = _get_header(headers, "Return-Path")
    if not return_path:
        return False

    envelope_domain = _extract_domain(parseaddr(return_path)[1])
    sender_domain = _extract_domain(sender)
    if not envelope_domain or not sender_domain:
        return False

    return envelope_domain != sender_domain
