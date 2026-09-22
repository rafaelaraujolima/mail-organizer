import json
from unittest.mock import MagicMock

import pytest

from mail_organizer.llm import ClassificationResult, OllamaClient, OllamaUnavailableError
from mail_organizer.providers.base import Message


def _make_message() -> Message:
    return Message(
        id="1", folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01",
        body_text="Hello world",
    )


def _mock_response(status_code=200, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.raise_for_status.return_value = None
    return response


def test_check_available_raises_when_connection_fails():
    session = MagicMock()
    session.get.side_effect = ConnectionError("refused")
    client = OllamaClient(session)

    with pytest.raises(OllamaUnavailableError):
        client.check_available()


def test_check_available_raises_on_non_200():
    session = MagicMock()
    session.get.return_value = _mock_response(status_code=500)
    client = OllamaClient(session)

    with pytest.raises(OllamaUnavailableError):
        client.check_available()


def test_check_available_raises_when_model_missing():
    session = MagicMock()
    session.get.return_value = _mock_response(json_body={"models": [{"name": "other:1b"}]})
    client = OllamaClient(session, model="llama3.2:3b")

    with pytest.raises(OllamaUnavailableError):
        client.check_available()


def test_check_available_succeeds_when_model_present():
    session = MagicMock()
    session.get.return_value = _mock_response(json_body={"models": [{"name": "llama3.2:3b"}]})
    client = OllamaClient(session, model="llama3.2:3b")

    client.check_available()  # should not raise


def test_classify_posts_prompt_and_parses_json_response():
    session = MagicMock()
    session.post.return_value = _mock_response(
        json_body={
            "response": json.dumps({"folder": "Promotions", "suspicious": False, "reason": "newsletter"})
        }
    )
    client = OllamaClient(session, model="llama3.2:3b")

    result = client.classify(_make_message(), existing_folders=["INBOX", "Promotions"], heuristic_flags=[])

    assert result == ClassificationResult(folder="Promotions", suspicious=False, reason="newsletter")
    call_kwargs = session.post.call_args.kwargs
    assert call_kwargs["json"]["model"] == "llama3.2:3b"
    assert "Promotions" in call_kwargs["json"]["prompt"]


def test_classify_defaults_missing_fields():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"response": json.dumps({})})
    client = OllamaClient(session)

    result = client.classify(_make_message(), existing_folders=[], heuristic_flags=[])

    assert result == ClassificationResult(folder=None, suspicious=False, reason="")
