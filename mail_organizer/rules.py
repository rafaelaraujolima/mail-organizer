# mail_organizer/rules.py
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

# The sender comes from an email header and ends up in a provider filter, so
# anything that is not a plain address is skipped instead of escaped.
SENDER_RE = re.compile(r"^[^\s@<>\"',;()\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class RuleCandidate:
    kind: str  # "sender" | "domain"
    value: str
    folder: str
    count: int


def _dominant_folder(folders: Counter, threshold: int) -> tuple[str, int] | None:
    ranked = folders.most_common()
    folder, count = ranked[0]
    if count < threshold:
        return None
    if len(ranked) > 1 and ranked[1][1] == count:
        return None
    return folder, count


def detect_rule_candidates(
    proposals: list[dict],
    existing_rules: list[tuple[str, str]],
    threshold: int = 3,
) -> list[RuleCandidate]:
    existing = {(kind, value.lower()) for kind, value in existing_rules}

    by_sender: dict[str, Counter] = defaultdict(Counter)
    for proposal in proposals:
        if proposal.get("action") != "move" or not proposal.get("target_folder"):
            continue
        sender = (proposal.get("sender") or "").strip().lower()
        if not SENDER_RE.match(sender):
            continue
        by_sender[sender][proposal["target_folder"]] += 1

    candidates: list[RuleCandidate] = []
    covered: set[str] = set()
    for sender, folders in by_sender.items():
        dominant = _dominant_folder(folders, threshold)
        if dominant is None:
            continue
        # Covered even when an existing rule suppresses the candidate: those
        # emails are already handled and must not feed a broader domain rule.
        covered.add(sender)
        if ("sender", sender) in existing:
            continue
        candidates.append(RuleCandidate("sender", sender, dominant[0], dominant[1]))

    by_domain: dict[str, Counter] = defaultdict(Counter)
    for sender, folders in by_sender.items():
        if sender in covered:
            continue
        domain = sender.split("@", 1)[1]
        if not DOMAIN_RE.match(domain):
            continue
        by_domain[domain].update(folders)

    for domain, folders in by_domain.items():
        dominant = _dominant_folder(folders, threshold)
        if dominant is None or ("domain", domain) in existing:
            continue
        candidates.append(RuleCandidate("domain", domain, dominant[0], dominant[1]))

    candidates.sort(key=lambda c: (-c.count, c.kind, c.value))
    return candidates
