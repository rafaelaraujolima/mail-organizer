# mail_organizer/rules.py
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

# The sender comes from an email header and ends up in a provider filter, so
# anything that is not a plain address is skipped instead of escaped.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_DOMAIN = rf"(?:{_LABEL}\.)+[A-Za-z]{{2,}}"
# Local part: no leading "-" or ".", no trailing ".", no "..".
_LOCAL = r"(?![-.])(?!.*\.\.)[A-Za-z0-9._%+-]*[A-Za-z0-9_%+-]"
SENDER_RE = re.compile(rf"{_LOCAL}@{_DOMAIN}")
DOMAIN_RE = re.compile(_DOMAIN)
MAX_ADDRESS_LENGTH = 254

# Rules must never move mail into a system label/folder. The list is name-based,
# so localized provider names (e.g. "Itens Excluídos") are not recognised.
SYSTEM_FOLDER_NAMES = frozenset({
    "inbox", "trash", "spam", "sent", "drafts", "draft", "unread", "starred",
    "important", "chat", "outbox", "junk", "junk email", "junk e-mail",
    "deleted items", "deleted", "sent items", "sent mail", "bin",
})


def is_system_folder(name: str) -> bool:
    normalized = (name or "").strip().lower()
    return normalized in SYSTEM_FOLDER_NAMES or normalized.startswith("category_")


def _valid_sender(sender: str) -> bool:
    return len(sender) <= MAX_ADDRESS_LENGTH and SENDER_RE.fullmatch(sender) is not None


def _valid_domain(domain: str) -> bool:
    return len(domain) <= MAX_ADDRESS_LENGTH and DOMAIN_RE.fullmatch(domain) is not None


@dataclass(frozen=True)
class RuleCandidate:
    kind: str  # "sender" | "domain"
    value: str
    folder: str
    count: int  # emails that go to `folder`
    total: int  # emails of the group considered, whatever their action or folder


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
    threshold = max(int(threshold), 1)
    existing = {(kind, value.lower()) for kind, value in existing_rules}

    # Every email of a sender is counted in `total` so the reason text can
    # disclose how many of them the rule does not cover; dominance itself only
    # looks at the moves.
    totals: Counter = Counter()
    by_sender: dict[str, Counter] = defaultdict(Counter)
    for proposal in proposals:
        if proposal.get("action") == "create_rule":
            continue
        listed_sender = (proposal.get("sender") or "").strip().lower()
        if _valid_sender(listed_sender):
            totals[listed_sender] += 1
        if proposal.get("action") != "move" or not proposal.get("target_folder"):
            continue
        if is_system_folder(proposal["target_folder"]):
            continue
        sender = (proposal.get("sender") or "").strip().lower()
        if not _valid_sender(sender):
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
        candidates.append(RuleCandidate("sender", sender, dominant[0], dominant[1], totals[sender]))

    by_domain: dict[str, Counter] = defaultdict(Counter)
    domain_totals: Counter = Counter()
    for sender, folders in by_sender.items():
        if sender in covered:
            continue
        domain = sender.split("@", 1)[1]
        if not _valid_domain(domain):
            continue
        by_domain[domain].update(folders)
    for sender, total in totals.items():
        if sender in covered:
            continue
        domain = sender.split("@", 1)[1]
        if domain in by_domain:
            domain_totals[domain] += total

    for domain, folders in by_domain.items():
        dominant = _dominant_folder(folders, threshold)
        if dominant is None or ("domain", domain) in existing:
            continue
        candidates.append(RuleCandidate("domain", domain, dominant[0], dominant[1], domain_totals[domain]))

    candidates.sort(key=lambda c: (-c.count, c.kind, c.value))
    return candidates
