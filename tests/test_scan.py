import logging
from unittest.mock import MagicMock

from mail_organizer.llm import ClassificationResult, OllamaUnavailableError
from mail_organizer.providers.base import Folder, Message
from mail_organizer.scan import run_scan


def _make_message(msg_id="msg-1", **overrides) -> Message:
    defaults = dict(
        id=msg_id, folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01",
        body_text="hello", snippet="hello snippet", headers={},
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_marks_job_failed_when_ollama_unavailable():
    db = MagicMock()
    provider = MagicMock()
    llm_client = MagicMock()
    llm_client.check_available.side_effect = OllamaUnavailableError("not running")

    run_scan(db, provider, llm_client, "job-1", messages=[_make_message()])

    db.mark_job_failed.assert_called_once_with("job-1", "not running")
    db.add_proposal.assert_not_called()
    provider.list_folders.assert_not_called()


def test_processes_each_message_and_records_proposal_and_progress():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX"), Folder(id="Promotions", name="Promotions")]
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(folder="Promotions", suspicious=False, reason="Newsletter")

    messages = [_make_message("msg-1"), _make_message("msg-2")]

    run_scan(db, provider, llm_client, "job-1", messages=messages)

    assert db.add_proposal.call_count == 2
    db.add_proposal.assert_any_call("job-1", "msg-1", "move", "Promotions", "Newsletter", sender="a@b.com", subject="Hi", date="2026-01-01", snippet="hello snippet")
    db.add_proposal.assert_any_call("job-1", "msg-2", "move", "Promotions", "Newsletter", sender="a@b.com", subject="Hi", date="2026-01-01", snippet="hello snippet")
    db.update_job_progress.assert_any_call("job-1", 1, "running")
    db.update_job_progress.assert_any_call("job-1", 2, "running")
    db.update_job_progress.assert_any_call("job-1", 2, "completed")
    db.mark_job_failed.assert_not_called()


def test_per_message_failure_is_recorded_as_error_and_does_not_stop_the_scan():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()
    llm_client.classify.side_effect = [RuntimeError("boom"), ClassificationResult(folder=None, suspicious=False, reason="")]

    messages = [_make_message("msg-1"), _make_message("msg-2")]

    run_scan(db, provider, llm_client, "job-1", messages=messages)

    db.add_proposal.assert_any_call("job-1", "msg-1", "error", None, "Erro ao analisar: boom", sender="a@b.com", subject="Hi", date="2026-01-01", snippet="hello snippet")
    db.add_proposal.assert_any_call("job-1", "msg-2", "keep", None, "Nenhuma ação sugerida", sender="a@b.com", subject="Hi", date="2026-01-01", snippet="hello snippet")
    db.update_job_progress.assert_any_call("job-1", 2, "completed")
    db.mark_job_failed.assert_not_called()


def test_provider_error_while_listing_folders_marks_job_failed():
    from mail_organizer.providers.errors import ProviderError

    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.side_effect = ProviderError("auth expired")
    llm_client = MagicMock()

    run_scan(db, provider, llm_client, "job-1", messages=[_make_message()])

    db.mark_job_failed.assert_called_once()
    assert "auth expired" in db.mark_job_failed.call_args.args[1]
    db.add_proposal.assert_not_called()


def test_error_recording_failure_does_not_abort_scan():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()
    llm_client.classify.side_effect = RuntimeError("boom")
    # The fallback db.add_proposal("error", ...) call itself fails (e.g. transient
    # DB error). This must not escape run_scan or leave the job stuck "running".
    db.add_proposal.side_effect = RuntimeError("db write failed")

    messages = [_make_message("msg-1")]

    run_scan(db, provider, llm_client, "job-1", messages=messages)

    db.update_job_progress.assert_any_call("job-1", 1, "completed")


def test_unanticipated_exception_before_loop_marks_job_failed_instead_of_hanging():
    # An exception type neither of the two specific pre-loop handlers catches
    # (e.g. a bare RuntimeError, standing in for things like requests'
    # JSONDecodeError or google.auth.exceptions.RefreshError that aren't
    # wrapped as OllamaUnavailableError/ProviderError) must still mark the
    # job failed rather than letting it escape run_scan and leave the job
    # stuck in "running" forever.
    db = MagicMock()
    provider = MagicMock()
    llm_client = MagicMock()
    llm_client.check_available.side_effect = RuntimeError("unexpected failure")

    run_scan(db, provider, llm_client, "job-1", messages=[_make_message()])

    db.mark_job_failed.assert_called_once()
    assert "unexpected failure" in db.mark_job_failed.call_args.args[1]
    db.add_proposal.assert_not_called()


def test_unguarded_progress_write_in_loop_marks_job_failed_via_backstop():
    # db.update_job_progress(..., "running") inside the loop's finally block
    # is not wrapped by the per-message try/except. If IT raises, the
    # backstop around the whole function body must still catch it and mark
    # the job failed instead of letting the loop abort silently.
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(folder=None, suspicious=False, reason="")
    db.update_job_progress.side_effect = RuntimeError("db write failed")

    messages = [_make_message("msg-1")]

    run_scan(db, provider, llm_client, "job-1", messages=messages)

    db.mark_job_failed.assert_called_once()
    assert "db write failed" in db.mark_job_failed.call_args.args[1]


def test_llm_hallucinated_folder_not_in_existing_folders_is_ignored():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX")]
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(
        folder="NonexistentFolder", suspicious=False, reason=""
    )

    messages = [_make_message("msg-1")]

    run_scan(db, provider, llm_client, "job-1", messages=messages)

    db.add_proposal.assert_any_call("job-1", "msg-1", "keep", None, "Nenhuma ação sugerida", sender="a@b.com", subject="Hi", date="2026-01-01", snippet="hello snippet")


def test_run_scan_integrates_with_a_real_database(tmp_path):
    from mail_organizer.crypto import load_or_create_key
    from mail_organizer.db import Database

    key = load_or_create_key(tmp_path / "secret.key")
    with Database(tmp_path / "test.db", key) as db:
        db.init_schema()
        db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc"})
        db.create_job("job-1", "acc-1", total=2)

        provider = MagicMock()
        provider.list_folders.return_value = [
            Folder(id="INBOX", name="INBOX"), Folder(id="Promotions", name="Promotions")
        ]
        llm_client = MagicMock()
        llm_client.classify.return_value = ClassificationResult(
            folder="Promotions", suspicious=False, reason="Newsletter"
        )

        messages = [_make_message("msg-1"), _make_message("msg-2")]

        run_scan(db, provider, llm_client, "job-1", messages=messages)

        proposals = db.list_proposals("job-1")
        assert len(proposals) == 2
        assert proposals[0] == {
            "id": 1, "message_id": "msg-1", "action": "move", "target_folder": "Promotions",
            "reason": "Newsletter", "applied_status": "pending", "applied_error": None,
            "sender": "a@b.com", "subject": "Hi", "date": "2026-01-01", "snippet": "hello snippet",
            "rule_kind": None, "rule_value": None, "rule_match_count": None,
        }
        job = db.get_job("job-1")
        assert job["status"] == "completed"


def test_empty_message_list_completes_immediately():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()

    run_scan(db, provider, llm_client, "job-1", messages=[])

    db.update_job_progress.assert_called_once_with("job-1", 0, "completed")
    db.add_proposal.assert_not_called()


def test_snippet_is_truncated_to_200_characters_and_none_becomes_empty():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(folder=None, suspicious=False, reason="")

    run_scan(db, provider, llm_client, "job-1", messages=[_make_message("msg-1", snippet="x" * 500)])

    assert db.add_proposal.call_args.kwargs["snippet"] == "x" * 200


def _real_db(tmp_path):
    from mail_organizer.crypto import load_or_create_key
    from mail_organizer.db import Database

    key = load_or_create_key(tmp_path / "secret.key")
    db = Database(tmp_path / "test.db", key)
    db.init_schema()
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc"})
    return db


def _promo_llm():
    llm_client = MagicMock()
    llm_client.classify.return_value = ClassificationResult(
        folder="Promotions", suspicious=False, reason="Newsletter"
    )
    return llm_client


def _rules_provider(supports=True):
    provider = MagicMock()
    provider.supports_rules.return_value = supports
    provider.list_folders.return_value = [Folder(id="Promotions", name="Promotions")]
    return provider


def _rule_proposals(db, job_id):
    return [p for p in db.list_proposals(job_id) if p["action"] == "create_rule"]


def test_scan_proposes_a_sender_rule_when_threshold_is_reached(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    rules = [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["message_id"] == ""
    assert rule["target_folder"] == "Promotions"
    assert rule["rule_kind"] == "sender"
    assert rule["rule_value"] == "news@shop.com"
    assert rule["rule_match_count"] == 3
    assert rule["sender"] == "news@shop.com"
    assert rule["reason"] == "3 de 3 emails deste lote vão para Promotions"
    assert db.get_job("job-1")["status"] == "completed"
    db.close()


def test_rule_reason_discloses_the_sender_emails_that_are_not_moves(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=5)
    llm_client = MagicMock()
    promo = ClassificationResult(folder="Promotions", suspicious=False, reason="Newsletter")
    nothing = ClassificationResult(folder=None, suspicious=False, reason="")
    llm_client.classify.side_effect = [promo, promo, promo, nothing, nothing]
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(5)]

    run_scan(db, _rules_provider(), llm_client, "job-1", messages=messages, rule_threshold=3)

    actions = sorted(p["action"] for p in db.list_proposals("job-1") if p["action"] != "create_rule")
    assert actions == ["keep", "keep", "move", "move", "move"]
    rules = _rule_proposals(db, "job-1")
    assert len(rules) == 1
    assert rules[0]["rule_match_count"] == 3
    assert rules[0]["reason"] == "3 de 5 emails deste lote vão para Promotions"
    db.close()


def test_scan_does_not_propose_rules_below_threshold(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=2)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(2)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []

    # Positive control: same messages, threshold lowered to 2 -> a rule appears.
    db.create_job("job-2", "acc-1", total=2)
    messages2 = [_make_message(f"j2-msg-{i}", sender="news@shop.com") for i in range(2)]
    run_scan(db, _rules_provider(), _promo_llm(), "job-2", messages=messages2, rule_threshold=2)

    assert len(_rule_proposals(db, "job-2")) == 1
    db.close()


def test_scan_does_not_propose_rules_when_provider_does_not_support_them(tmp_path):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(supports=False), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []
    assert db.get_job("job-1")["status"] == "completed"

    # Positive control: same messages, provider supporting rules -> a rule appears.
    db.create_job("job-2", "acc-1", total=3)
    messages2 = [_make_message(f"j2-msg-{i}", sender="news@shop.com") for i in range(3)]
    run_scan(db, _rules_provider(supports=True), _promo_llm(), "job-2", messages=messages2, rule_threshold=3)

    assert len(_rule_proposals(db, "job-2")) == 1
    db.close()


def test_scan_skips_a_rule_that_was_already_applied_for_the_account(tmp_path):
    db = _real_db(tmp_path)
    db.add_applied_rule("acc-1", "sender", "news@shop.com", "Promotions", "rule-1")
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]

    run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert [p for p in db.list_proposals("job-1") if p["action"] == "create_rule"] == []

    # Positive control: a different account with no applied rule -> a rule appears.
    db.save_account("acc-2", "gmail", "other@gmail.com", {"refresh_token": "def"})
    db.create_job("job-2", "acc-2", total=3)
    messages2 = [_make_message(f"j2-msg-{i}", sender="news@shop.com") for i in range(3)]
    run_scan(db, _rules_provider(), _promo_llm(), "job-2", messages=messages2, rule_threshold=3)

    assert len(_rule_proposals(db, "job-2")) == 1
    db.close()


def test_rule_detection_failure_does_not_fail_the_scan(tmp_path, monkeypatch, caplog):
    db = _real_db(tmp_path)
    db.create_job("job-1", "acc-1", total=3)
    messages = [_make_message(f"msg-{i}", sender="news@shop.com") for i in range(3)]
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("mail_organizer.scan.detect_rule_candidates", boom)

    with caplog.at_level(logging.WARNING, logger="mail_organizer.scan"):
        run_scan(db, _rules_provider(), _promo_llm(), "job-1", messages=messages, rule_threshold=3)

    assert len(calls) == 1
    records = [r for r in caplog.records if r.name == "mail_organizer.scan"]
    assert len(records) == 1
    assert "job-1" in records[0].getMessage()
    assert records[0].exc_info is not None
    job = db.get_job("job-1")
    assert job["status"] == "completed"
    assert len(db.list_proposals("job-1")) == 3
    db.close()
