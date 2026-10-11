import logging
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import EmailProvider, Folder, Message
from mail_organizer.providers.errors import ProviderAuthError, ProviderError

SELECTED_FOLDERS: list[str] = []


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials
        self.moved = []
        self.deleted = []

    def select_folder(self, folder):
        SELECTED_FOLDERS.append(folder)

    def list_folders(self):
        return [Folder(id="Label_7", name="Promotions")]

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        return Message(
            id=message_id, folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01",
            body_html='<p>Hi</p><script>alert(1)</script>',
        )

    def move_message(self, message_id, target_folder):
        self.moved.append((message_id, target_folder))

    def delete_message(self, message_id):
        self.deleted.append(message_id)


class _FailingMoveProvider(_FakeProvider):
    def move_message(self, message_id, target_folder):
        raise ProviderError("rate limited")


class _RuleProvider(_FakeProvider):
    created = []

    def supports_rules(self):
        return True

    def create_rule(self, condition, target_folder):
        _RuleProvider.created.append((condition.sender, condition.domain, target_folder))
        return "rule-1"


def _broken_factory(credentials):
    raise ProviderAuthError("token refresh failed")


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingMoveProvider, "broken": _broken_factory, "rule": _RuleProvider}


@pytest.fixture(autouse=True)
def _reset_selected_folders():
    SELECTED_FOLDERS.clear()
    _RuleProvider.created.clear()


def _seed_proposal(db, provider_type="fake", action="move", target_folder="Promotions", folder=None):
    db.save_account("acc-1", provider_type, "x", {})
    db.create_job("job-1", "acc-1", total=1, folder=folder)
    db.add_proposal("job-1", "msg-1", action, target_folder, "some reason")
    return db.list_proposals("job-1")[0]["id"]


def test_approve_move_proposal_applies_it_and_marks_applied(client, db):
    proposal_id = _seed_proposal(db)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"


def test_approve_returns_404_for_unknown_proposal(client):
    response = client.post("/proposals/999/approve")

    assert response.status_code == 404


def test_approve_returns_409_and_does_not_touch_the_provider_when_already_applied(client, db, monkeypatch):
    proposal_id = _seed_proposal(db)
    client.post(f"/proposals/{proposal_id}/approve")

    apply_spy = MagicMock()
    monkeypatch.setattr("mail_organizer.api.routes_proposals.apply_proposal", apply_spy)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 409
    apply_spy.assert_not_called()


def test_approve_returns_502_and_stays_retryable_when_apply_fails(client, db):
    proposal_id = _seed_proposal(db, provider_type="failing")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    proposal = db.get_proposal(proposal_id)
    assert proposal["applied_status"] == "pending"
    assert proposal["applied_error"]


def test_approve_returns_502_when_provider_cannot_be_built(client, db):
    proposal_id = _seed_proposal(db, provider_type="broken")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    proposal = db.get_proposal(proposal_id)
    assert proposal["applied_status"] == "pending"
    assert proposal["applied_error"]


def test_approve_selects_the_jobs_folder_before_applying(client, db):
    proposal_id = _seed_proposal(db, folder="INBOX")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert SELECTED_FOLDERS == ["INBOX"]


def test_reject_marks_proposal_rejected_without_calling_provider(client, db):
    proposal_id = _seed_proposal(db)

    response = client.post(f"/proposals/{proposal_id}/reject")

    assert response.status_code == 200
    assert db.get_proposal(proposal_id)["applied_status"] == "rejected"


def test_reject_returns_409_when_already_applied(client, db):
    proposal_id = _seed_proposal(db)
    client.post(f"/proposals/{proposal_id}/approve")

    response = client.post(f"/proposals/{proposal_id}/reject")

    assert response.status_code == 409
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"


def test_batch_approve_reports_per_id_results(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=2)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "r1")
    db.add_proposal("job-1", "msg-2", "move", "Promotions", "r2")
    ids = [p["id"] for p in db.list_proposals("job-1")]

    response = client.post("/proposals/batch-approve", json={"ids": ids + [999]})

    assert response.status_code == 200
    results = response.json()
    assert results[str(ids[0])] == "ok"
    assert results[str(ids[1])] == "ok"
    assert "error" in results["999"]


def test_batch_approve_continues_after_one_proposal_fails(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=2)
    # "Ghost" is not in _FakeProvider.list_folders(), so this one fails to apply;
    # the proposal after it must still be applied.
    db.add_proposal("job-1", "msg-1", "move", "Ghost", "r1")
    db.add_proposal("job-1", "msg-2", "move", "Promotions", "r2")
    ids = [p["id"] for p in db.list_proposals("job-1")]

    response = client.post("/proposals/batch-approve", json={"ids": ids})

    results = response.json()
    assert results[str(ids[0])].startswith("error:")
    assert "Ghost" in results[str(ids[0])]
    assert results[str(ids[1])] == "ok"
    assert db.get_proposal(ids[0])["applied_status"] == "pending"
    assert db.get_proposal(ids[1])["applied_status"] == "applied"


def test_batch_approve_continues_when_one_account_provider_cannot_be_built(client, db):
    db.save_account("acc-bad", "broken", "x", {})
    db.save_account("acc-ok", "fake", "x", {})
    db.create_job("job-bad", "acc-bad", total=1)
    db.create_job("job-ok", "acc-ok", total=1)
    db.add_proposal("job-bad", "msg-1", "move", "Promotions", "r1")
    db.add_proposal("job-ok", "msg-2", "move", "Promotions", "r2")
    bad_id = db.list_proposals("job-bad")[0]["id"]
    ok_id = db.list_proposals("job-ok")[0]["id"]

    response = client.post("/proposals/batch-approve", json={"ids": [bad_id, ok_id]})

    results = response.json()
    assert results[str(bad_id)].startswith("error:")
    assert results[str(ok_id)] == "ok"
    assert db.get_proposal(bad_id)["applied_status"] == "pending"


def test_get_message_content_returns_sanitized_html(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=1)

    response = client.get("/jobs/job-1/messages/msg-1/content")

    assert response.status_code == 200
    assert response.json() == {"html": "<p>Hi</p>"}


def test_get_message_content_selects_the_jobs_folder(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=1, folder="INBOX")

    response = client.get("/jobs/job-1/messages/msg-1/content")

    assert response.status_code == 200
    assert SELECTED_FOLDERS == ["INBOX"]


def test_get_message_content_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist/messages/msg-1/content")

    assert response.status_code == 404


def test_get_message_content_returns_502_when_provider_cannot_be_built(client, db):
    db.save_account("acc-1", "broken", "x", {})
    db.create_job("job-1", "acc-1", total=1)

    response = client.get("/jobs/job-1/messages/msg-1/content")

    assert response.status_code == 502


class _SlowProvider(_FakeProvider):
    calls: list = []

    def move_message(self, message_id, target_folder):
        import time

        _SlowProvider.calls.append((message_id, target_folder))
        time.sleep(0.2)


def test_concurrent_approves_call_the_provider_once(db, provider_factories):
    import threading

    from fastapi.testclient import TestClient

    from mail_organizer.api.app import create_app

    _SlowProvider.calls = []
    app = create_app(db, {"slow": _SlowProvider})
    proposal_id = _seed_proposal(db, provider_type="slow")
    statuses = []

    def fire():
        with TestClient(app, headers={"X-Requested-With": "mail-organizer"}) as c:
            statuses.append(c.post(f"/proposals/{proposal_id}/approve").status_code)

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(statuses) == [200, 409]
    assert len(_SlowProvider.calls) == 1
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"


def test_batch_approve_dedupes_ids(client, db):
    _SlowProvider.calls = []
    proposal_id = _seed_proposal(db)

    response = client.post("/proposals/batch-approve", json={"ids": [proposal_id, proposal_id]})

    assert response.json() == {str(proposal_id): "ok"}


@pytest.mark.parametrize("exc_type", [OSError, TimeoutError, RuntimeError])
def test_batch_approve_survives_unexpected_provider_exceptions(db, exc_type):
    from fastapi.testclient import TestClient

    from mail_organizer.api.app import create_app

    class _Raising(_FakeProvider):
        def move_message(self, message_id, target_folder):
            if message_id == "msg-1":
                raise exc_type("kaboom")

    client = TestClient(create_app(db, {"raising": _Raising}), headers={"X-Requested-With": "mail-organizer"})
    db.save_account("acc-1", "raising", "x", {})
    db.create_job("job-1", "acc-1", total=2)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "r1")
    db.add_proposal("job-1", "msg-2", "move", "Promotions", "r2")
    ids = [p["id"] for p in db.list_proposals("job-1")]

    response = client.post("/proposals/batch-approve", json={"ids": ids})

    assert response.status_code == 200
    results = response.json()
    assert results[str(ids[0])].startswith("error:")
    assert "kaboom" in results[str(ids[0])]
    assert results[str(ids[1])] == "ok"


def test_single_approve_returns_502_when_provider_raises_unexpected_error(db):
    from fastapi.testclient import TestClient

    from mail_organizer.api.app import create_app

    class _Raising(_FakeProvider):
        def delete_message(self, message_id):
            raise TimeoutError("slow")

    client = TestClient(create_app(db, {"raising": _Raising}), headers={"X-Requested-With": "mail-organizer"})
    proposal_id = _seed_proposal(db, provider_type="raising", action="flag_delete", target_folder=None)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    proposal = db.get_proposal(proposal_id)
    assert proposal["applied_status"] == "pending"
    assert "slow" in proposal["applied_error"]


def _seed_rule_proposal(db, provider_type="rule", folder_name="Promotions", rule_kind="sender", rule_value="news@shop.com"):
    db.save_account("acc-1", provider_type, "x", {})
    db.create_job("job-1", "acc-1", total=0)
    db.add_proposal(
        "job-1", "", "create_rule", folder_name, "3 emails deste lote vão para Promotions",
        sender=rule_value, rule_kind=rule_kind, rule_value=rule_value, rule_match_count=3,
    )
    return db.list_proposals("job-1")[0]["id"]


def test_approve_rule_creates_it_and_records_it(client, db):
    proposal_id = _seed_rule_proposal(db)

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert _RuleProvider.created == [("news@shop.com", None, "Label_7")]
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"
    assert db.list_applied_rules("acc-1") == [
        {"kind": "sender", "value": "news@shop.com", "folder": "Promotions", "provider_rule_id": "rule-1"}
    ]


def test_approve_domain_rule_uses_a_domain_condition(client, db):
    proposal_id = _seed_rule_proposal(db, rule_kind="domain", rule_value="shop.com")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert _RuleProvider.created == [(None, "shop.com", "Label_7")]


def test_approving_a_rule_twice_creates_it_once(client, db):
    proposal_id = _seed_rule_proposal(db)
    client.post(f"/proposals/{proposal_id}/approve")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 409
    assert len(_RuleProvider.created) == 1


def test_approve_rule_fails_when_target_folder_no_longer_exists(client, db):
    proposal_id = _seed_rule_proposal(db, folder_name="Ghost Folder")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    assert "Ghost Folder" in response.json()["detail"]
    proposal = db.get_proposal(proposal_id)
    assert proposal["applied_status"] == "pending"
    assert proposal["applied_error"]
    assert db.list_applied_rules("acc-1") == []
    assert _RuleProvider.created == []


def test_approve_rule_fails_for_a_provider_without_rule_support(client, db):
    proposal_id = _seed_rule_proposal(db, provider_type="fake")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    assert db.get_proposal(proposal_id)["applied_status"] == "pending"
    assert db.list_applied_rules("acc-1") == []


def test_rule_stays_applied_when_recording_it_locally_fails(client, db, monkeypatch, caplog):
    proposal_id = _seed_rule_proposal(db)
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "add_applied_rule", boom)

    with caplog.at_level(logging.WARNING, logger="mail_organizer.api.routes_proposals"):
        response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    records = [r for r in caplog.records if r.name == "mail_organizer.api.routes_proposals"]
    assert len(records) == 1
    assert str(proposal_id) in records[0].getMessage()
    assert records[0].exc_info is not None
    assert calls == [("acc-1", "sender", "news@shop.com", "Promotions", "rule-1")]
    assert db.get_proposal(proposal_id)["applied_status"] == "applied"
    assert client.post(f"/proposals/{proposal_id}/approve").status_code == 409
    assert len(_RuleProvider.created) == 1


def test_batch_approve_applies_email_and_rule_proposals_independently(client, db):
    db.save_account("acc-1", "rule", "x", {})
    db.create_job("job-1", "acc-1", total=1)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "r1")
    db.add_proposal(
        "job-1", "", "create_rule", ("Ghost Folder"), "r2",
        sender="news@shop.com", rule_kind="sender", rule_value="news@shop.com", rule_match_count=3,
    )
    ids = [p["id"] for p in db.list_proposals("job-1")]

    response = client.post("/proposals/batch-approve", json={"ids": ids})

    results = response.json()
    assert results[str(ids[0])] == "ok"
    assert results[str(ids[1])].startswith("error:")
    assert db.get_proposal(ids[0])["applied_status"] == "applied"
    assert db.get_proposal(ids[1])["applied_status"] == "pending"


def _add_rule_proposal(db, job_id, rule_value, rule_kind="sender"):
    db.add_proposal(
        job_id, "", "create_rule", "Promotions", "3 de 3 emails deste lote vão para Promotions",
        sender=rule_value, rule_kind=rule_kind, rule_value=rule_value, rule_match_count=3,
    )
    return db.list_proposals(job_id)[-1]["id"]


def test_second_proposal_for_an_existing_rule_does_not_call_the_provider(client, db):
    first_id = _seed_rule_proposal(db)
    db.create_job("job-2", "acc-1", total=0)
    second_id = _add_rule_proposal(db, "job-2", "News@Shop.com")

    assert client.post(f"/proposals/{first_id}/approve").status_code == 200
    assert len(_RuleProvider.created) == 1

    response = client.post(f"/proposals/{second_id}/approve")

    assert response.status_code == 502
    assert "news@shop.com" in response.json()["detail"].lower()
    assert "Promotions" in response.json()["detail"]
    assert len(_RuleProvider.created) == 1
    second = db.get_proposal(second_id)
    assert second["applied_status"] == "pending"
    assert second["applied_error"]
    assert len(db.list_applied_rules("acc-1")) == 1


def test_proposal_for_a_different_sender_is_still_applied(client, db):
    first_id = _seed_rule_proposal(db)
    db.create_job("job-2", "acc-1", total=0)
    other_id = _add_rule_proposal(db, "job-2", "other@shop.com")

    assert client.post(f"/proposals/{first_id}/approve").status_code == 200
    response = client.post(f"/proposals/{other_id}/approve")

    assert response.status_code == 200
    assert len(_RuleProvider.created) == 2
    assert len(db.list_applied_rules("acc-1")) == 2


def test_rule_already_recorded_locally_is_not_created_again_on_retry(client, db):
    proposal_id = _seed_rule_proposal(db)
    db.add_applied_rule("acc-1", "sender", "news@shop.com", "Promotions", "rule-0")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 502
    assert _RuleProvider.created == []
    assert db.get_proposal(proposal_id)["applied_status"] == "pending"
    assert len(db.list_applied_rules("acc-1")) == 1


def test_same_value_with_a_different_kind_is_not_a_duplicate(client, db):
    db.save_account("acc-1", "rule", "x", {})
    db.create_job("job-1", "acc-1", total=0)
    db.add_applied_rule("acc-1", "domain", "shop.com", "Promotions", "rule-0")
    proposal_id = _add_rule_proposal(db, "job-1", "shop.com", rule_kind="sender")

    response = client.post(f"/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    assert len(_RuleProvider.created) == 1
