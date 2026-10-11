import pytest
from fastapi.testclient import TestClient

from mail_organizer.api.app import create_app

HEADERS = {"X-Requested-With": "mail-organizer"}


@pytest.fixture
def bare_client(app):
    return TestClient(app)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/proposals/1/approve", None),
        ("/proposals/1/reject", None),
        ("/proposals/batch-approve", {"ids": [1]}),
        ("/scan", {"account_id": "a", "folder": "INBOX", "filters": {}}),
        ("/accounts/imap", {"display_name": "x", "host": "h", "username": "u", "password": "p"}),
    ],
)
def test_mutating_requests_without_the_custom_header_get_403(bare_client, path, body):
    response = bare_client.post(path, json=body, headers={"Content-Type": "text/plain"} if body is None else None)

    assert response.status_code == 403


def test_wrong_header_value_is_rejected(bare_client):
    response = bare_client.post("/proposals/1/reject", headers={"X-Requested-With": "other"})

    assert response.status_code == 403


def test_get_endpoints_do_not_require_the_header(bare_client):
    assert bare_client.get("/accounts").status_code == 200
    assert bare_client.get("/jobs/nope").status_code == 404


def test_post_with_the_header_reaches_the_route(bare_client):
    response = bare_client.post("/proposals/999/reject", headers=HEADERS)

    assert response.status_code == 404


def test_allowed_hosts_rejects_unknown_host_header(db):
    client = TestClient(create_app(db, {}, allowed_hosts=["localhost"]), headers=HEADERS)

    assert client.get("/accounts", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/accounts", headers={"Host": "localhost"}).status_code == 200


def test_no_allowed_hosts_means_no_host_check(db):
    client = TestClient(create_app(db, {}))

    assert client.get("/accounts", headers={"Host": "evil.example"}).status_code == 200
