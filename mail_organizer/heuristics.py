import re
from dataclasses import dataclass, field
from email.utils import parseaddr

from mail_organizer.providers.base import Message


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


SHORTENER_DOMAINS = {"bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly"}


def extract_links(html: str | None) -> list[str]:
    if not html:
        return []
    return re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)


def _looks_like_spoof(domain: str, expected_domain: str) -> bool:
    base = expected_domain.split(".")[0]
    return base in domain and domain != expected_domain


def has_suspicious_links(html: str | None, expected_domain: str | None = None) -> bool:
    for link in extract_links(html):
        match = re.match(r"https?://([^/]+)", link, re.IGNORECASE)
        if not match:
            continue
        domain = match.group(1).lower().split(":")[0]
        if domain in SHORTENER_DOMAINS:
            return True
        if expected_domain and domain != expected_domain and _looks_like_spoof(domain, expected_domain):
            return True
    return False


@dataclass
class HeuristicResult:
    auth: AuthResult
    domain_mismatch: bool
    suspicious_links: bool
    flags: list[str] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return bool(self.flags)


def analyze_message(message: Message) -> HeuristicResult:
    auth = parse_authentication_results(message.headers)
    domain_mismatch = detect_domain_mismatch(message.sender, message.headers)
    suspicious_links = has_suspicious_links(message.body_html, _extract_domain(message.sender))

    flags = []
    if auth.spf == "fail":
        flags.append("spf_fail")
    if auth.dkim == "fail":
        flags.append("dkim_fail")
    if auth.dmarc == "fail":
        flags.append("dmarc_fail")
    if domain_mismatch:
        flags.append("domain_mismatch")
    if suspicious_links:
        flags.append("suspicious_links")

    return HeuristicResult(
        auth=auth,
        domain_mismatch=domain_mismatch,
        suspicious_links=suspicious_links,
        flags=flags,
    )
