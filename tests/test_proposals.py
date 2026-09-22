from mail_organizer.heuristics import AuthResult, HeuristicResult
from mail_organizer.llm import ClassificationResult
from mail_organizer.proposals import Proposal, build_proposal
from mail_organizer.providers.base import Message


def _make_message() -> Message:
    return Message(id="msg-1", folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01")


def _heuristic(flags=None) -> HeuristicResult:
    return HeuristicResult(
        auth=AuthResult(), domain_mismatch=False, suspicious_links=False, flags=flags or []
    )


def test_heuristic_suspicion_produces_flag_delete_proposal():
    result = build_proposal(
        _make_message(),
        _heuristic(flags=["spf_fail", "domain_mismatch"]),
        ClassificationResult(folder=None, suspicious=False, reason=""),
    )

    assert result.action == "flag_delete"
    assert result.target_folder is None
    assert "spf_fail" in result.reason
    assert "domain_mismatch" in result.reason


def test_llm_suspicion_produces_flag_delete_proposal():
    result = build_proposal(
        _make_message(),
        _heuristic(),
        ClassificationResult(folder=None, suspicious=True, reason="Parece phishing"),
    )

    assert result.action == "flag_delete"
    assert result.reason == "Parece phishing"


def test_llm_folder_suggestion_produces_move_proposal():
    result = build_proposal(
        _make_message(),
        _heuristic(),
        ClassificationResult(folder="Promotions", suspicious=False, reason="Newsletter"),
    )

    assert result.action == "move"
    assert result.target_folder == "Promotions"
    assert result.reason == "Newsletter"


def test_no_suspicion_and_no_folder_produces_keep_proposal():
    result = build_proposal(
        _make_message(),
        _heuristic(),
        ClassificationResult(folder=None, suspicious=False, reason=""),
    )

    assert result.action == "keep"
    assert result.target_folder is None
    assert result.reason  # always has a non-empty justification


def test_proposal_always_carries_the_message_id():
    result = build_proposal(
        _make_message(),
        _heuristic(),
        ClassificationResult(folder="X", suspicious=False, reason="r"),
    )

    assert result.message_id == "msg-1"
