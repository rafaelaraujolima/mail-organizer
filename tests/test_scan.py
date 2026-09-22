from unittest.mock import MagicMock

from mail_organizer.llm import ClassificationResult, OllamaUnavailableError
from mail_organizer.providers.base import Folder, Message
from mail_organizer.scan import run_scan


def _make_message(msg_id="msg-1", **overrides) -> Message:
    defaults = dict(
        id=msg_id, folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01",
        body_text="hello", headers={},
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
    db.add_proposal.assert_any_call("job-1", "msg-1", "move", "Promotions", "Newsletter")
    db.add_proposal.assert_any_call("job-1", "msg-2", "move", "Promotions", "Newsletter")
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

    db.add_proposal.assert_any_call("job-1", "msg-1", "error", None, "Erro ao analisar: boom")
    db.add_proposal.assert_any_call("job-1", "msg-2", "keep", None, "Nenhuma ação sugerida")
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

    db.add_proposal.assert_any_call("job-1", "msg-1", "keep", None, "Nenhuma ação sugerida")


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
            "message_id": "msg-1", "action": "move", "target_folder": "Promotions", "reason": "Newsletter"
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
