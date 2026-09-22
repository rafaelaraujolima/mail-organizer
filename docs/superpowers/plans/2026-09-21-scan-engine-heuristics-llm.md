# Scan Engine (Heuristics + LLM Classification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the technical phishing heuristics, the local-LLM (Ollama) classification client, the proposal-generation logic that combines them, and the scan-engine orchestration that turns a list of `Message`s into stored `Proposal`s and job progress — the second of four planned subsystems (connectors+persistence is done; frontend and rules-proposal come after this).

**Architecture:** Four small, independently-testable modules — `mail_organizer/heuristics.py` (pure functions, no I/O), `mail_organizer/llm.py` (an `OllamaClient` built via the same dependency-injection pattern as the providers, so tests mock the HTTP session), `mail_organizer/proposals.py` (pure combination logic), and `mail_organizer/scan.py` (the orchestration loop) — plus additions to the existing `mail_organizer/db.py` for storing proposals and job failures. This plan does **not** add FastAPI routes, `BackgroundTasks` wiring, or the frontend — those belong to the next plan, which will call `create_job`, list messages via an `EmailProvider`, then invoke this plan's `run_scan(...)`.

**Tech Stack:** Python 3.11+ (matches the existing package), stdlib `re`/`email`/`json` for heuristics, `requests` for the Ollama HTTP API (already a dependency, used the same way `GraphProvider` uses it), `pytest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-21-mail-organizer-design.md`

## Global Constraints

- **Heurísticas técnicas** (rápidas, sem LLM) devem cobrir: SPF/DKIM/DMARC do header, domínio do remetente vs. domínio alegado, links suspeitos.
- **Classificação via LLM local** (Ollama): sugestão de pasta/categoria com base no conteúdo + pastas já existentes na caixa; sinalização de suspeita/irrelevância combinando com o resultado das heurísticas.
- Toda proposta gerada é: mover para pasta X | sinalizar como possível phishing/spam com sugestão de exclusão | manter como está — **sempre com justificativa curta**.
- **Falha do Ollama** (não está rodando / modelo não baixado): detectada **no início do scan**, com orientação clara — não deixa o job pendurado.
- **Falha ao processar um email específico:** não derruba o job inteiro; email marcado "erro ao analisar", pulado, reportado ao final para revisão manual.
- **Testes:** heurísticas de phishing (parsing SPF/DKIM, detecção de domínio spoofado, extração de links) são puras e isoladas (sem rede, sem LLM). Testes de classificação LLM contra o Ollama real são **opcionais e skippable** se Ollama não estiver disponível no ambiente, e verificam apenas o formato esperado da resposta — não a qualidade da classificação.
- **Não** guarda histórico de decisões de aprovação/rejeição (already enforced by `db.py` — this plan only adds pre-decision proposal storage, tied to a job, which is the working state the frontend polls, not a decision log).
- Nada é executado automaticamente — this plan only *proposes* (writes rows to the `proposals` table); applying an approved proposal is a future plan's job.

---

### Task 1: SPF/DKIM/DMARC heuristic

**Files:**
- Create: `mail_organizer/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Produces:
  - `@dataclass AuthResult` with fields `spf: str | None = None, dkim: str | None = None, dmarc: str | None = None`
  - `parse_authentication_results(headers: dict) -> AuthResult`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuristics.py
from mail_organizer.heuristics import AuthResult, parse_authentication_results


def test_parses_all_three_mechanisms_when_present():
    headers = {
        "Authentication-Results": (
            "mx.google.com; spf=pass smtp.mailfrom=foo@bar.com; "
            "dkim=fail header.i=@bar.com; dmarc=pass (p=REJECT) header.from=bar.com"
        )
    }

    result = parse_authentication_results(headers)

    assert result == AuthResult(spf="pass", dkim="fail", dmarc="pass")


def test_returns_all_none_when_header_missing():
    result = parse_authentication_results({})

    assert result == AuthResult(spf=None, dkim=None, dmarc=None)


def test_header_lookup_is_case_insensitive():
    headers = {"authentication-results": "spf=fail"}

    result = parse_authentication_results(headers)

    assert result.spf == "fail"


def test_missing_mechanism_stays_none():
    headers = {"Authentication-Results": "spf=pass"}

    result = parse_authentication_results(headers)

    assert result == AuthResult(spf="pass", dkim=None, dmarc=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heuristics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.heuristics'`

- [ ] **Step 3: Implement heuristics.py**

```python
# mail_organizer/heuristics.py
import re
from dataclasses import dataclass


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heuristics.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/heuristics.py tests/test_heuristics.py
git commit -m "feat: add SPF/DKIM/DMARC authentication-results parsing"
```

---

### Task 2: Domain-mismatch heuristic

**Files:**
- Modify: `mail_organizer/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Consumes: `_get_header` (private helper from Task 1, same file).
- Produces: `detect_domain_mismatch(sender: str, headers: dict) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_heuristics.py
from mail_organizer.heuristics import detect_domain_mismatch


def test_detects_mismatch_between_sender_and_return_path():
    headers = {"Return-Path": "<bounce@evil.com>"}

    assert detect_domain_mismatch("victim@bank.com", headers) is True


def test_no_mismatch_when_domains_match():
    headers = {"Return-Path": "<bounce@bank.com>"}

    assert detect_domain_mismatch("victim@bank.com", headers) is False


def test_no_mismatch_when_return_path_header_missing():
    assert detect_domain_mismatch("victim@bank.com", {}) is False


def test_no_mismatch_when_sender_has_no_domain():
    headers = {"Return-Path": "<bounce@evil.com>"}

    assert detect_domain_mismatch("", headers) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heuristics.py -v -k domain_mismatch`
Expected: FAIL with `ImportError: cannot import name 'detect_domain_mismatch'`

- [ ] **Step 3: Implement**

```python
# add to mail_organizer/heuristics.py
from email.utils import parseaddr


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heuristics.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/heuristics.py tests/test_heuristics.py
git commit -m "feat: add sender/Return-Path domain-mismatch heuristic"
```

---

### Task 3: Suspicious-link heuristic

**Files:**
- Modify: `mail_organizer/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Produces:
  - `extract_links(html: str) -> list[str]`
  - `has_suspicious_links(html: str, expected_domain: str | None = None) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_heuristics.py
from mail_organizer.heuristics import extract_links, has_suspicious_links


def test_extract_links_finds_href_urls():
    html = '<a href="https://example.com/a">A</a> <a href="http://x.com">B</a>'

    assert extract_links(html) == ["https://example.com/a", "http://x.com"]


def test_extract_links_returns_empty_list_for_empty_html():
    assert extract_links("") == []
    assert extract_links(None) == []


def test_has_suspicious_links_true_for_url_shortener():
    html = '<a href="https://bit.ly/abc123">click</a>'

    assert has_suspicious_links(html) is True


def test_has_suspicious_links_true_for_lookalike_domain():
    html = '<a href="https://paypal.com.evil.com/login">login</a>'

    assert has_suspicious_links(html, expected_domain="paypal.com") is True


def test_has_suspicious_links_false_for_legitimate_matching_domain():
    html = '<a href="https://paypal.com/login">login</a>'

    assert has_suspicious_links(html, expected_domain="paypal.com") is False


def test_has_suspicious_links_false_for_empty_html():
    assert has_suspicious_links("") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heuristics.py -v -k "extract_links or suspicious_links"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# add to mail_organizer/heuristics.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heuristics.py -v`
Expected: PASS (14 tests total)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/heuristics.py tests/test_heuristics.py
git commit -m "feat: add suspicious-link extraction heuristic"
```

---

### Task 4: Combine heuristics into analyze_message

**Files:**
- Modify: `mail_organizer/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Consumes: `mail_organizer.providers.base.Message` (existing, from the connectors plan); `AuthResult`, `parse_authentication_results`, `detect_domain_mismatch`, `has_suspicious_links`, `_extract_domain` (all from this file, Tasks 1-3).
- Produces:
  - `@dataclass HeuristicResult` with fields `auth: AuthResult, domain_mismatch: bool, suspicious_links: bool, flags: list[str]`, and a `is_suspicious` property (`bool(self.flags)`).
  - `analyze_message(message: Message) -> HeuristicResult`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_heuristics.py
from mail_organizer.heuristics import HeuristicResult, analyze_message
from mail_organizer.providers.base import Message


def _make_message(**overrides) -> Message:
    defaults = dict(
        id="1", folder="INBOX", sender="a@b.com", subject="Hi", date="2026-01-01",
        body_html="", headers={},
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_analyze_message_flags_spf_failure():
    message = _make_message(headers={"Authentication-Results": "spf=fail"})

    result = analyze_message(message)

    assert "spf_fail" in result.flags
    assert result.is_suspicious is True


def test_analyze_message_flags_domain_mismatch():
    message = _make_message(sender="victim@bank.com", headers={"Return-Path": "<x@evil.com>"})

    result = analyze_message(message)

    assert "domain_mismatch" in result.flags
    assert result.is_suspicious is True


def test_analyze_message_flags_suspicious_links():
    message = _make_message(body_html='<a href="https://bit.ly/x">click</a>')

    result = analyze_message(message)

    assert "suspicious_links" in result.flags


def test_analyze_message_clean_message_has_no_flags():
    message = _make_message(
        headers={"Authentication-Results": "spf=pass dkim=pass dmarc=pass"},
    )

    result = analyze_message(message)

    assert result.flags == []
    assert result.is_suspicious is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heuristics.py -v -k analyze_message`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# add to mail_organizer/heuristics.py
from dataclasses import field

from mail_organizer.providers.base import Message


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
```

Note: move the `from dataclasses import dataclass, field` import to the top of the file (single import line) rather than a local import — adjust the existing `from dataclasses import dataclass` line from Task 1 to `from dataclasses import dataclass, field`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heuristics.py -v`
Expected: PASS (18 tests total)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/heuristics.py tests/test_heuristics.py
git commit -m "feat: combine heuristics into analyze_message"
```

---

### Task 5: Ollama LLM client

**Files:**
- Create: `mail_organizer/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `mail_organizer.providers.base.Message` (existing).
- Produces:
  - `class OllamaUnavailableError(Exception)`
  - `@dataclass ClassificationResult` with fields `folder: str | None, suspicious: bool, reason: str`
  - `class OllamaClient`, constructor `OllamaClient(session, base_url: str = "http://localhost:11434", model: str = "llama3.2:3b")` where `session` is an already-configured `requests.Session`-like object (injected for testability with `unittest.mock.MagicMock`, same pattern as `GraphProvider`).
    - `.check_available() -> None` — raises `OllamaUnavailableError` if unreachable, non-200, or the model isn't in the tags list.
    - `.classify(message: Message, existing_folders: list[str], heuristic_flags: list[str]) -> ClassificationResult`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.llm'`

- [ ] **Step 3: Implement llm.py**

```python
# mail_organizer/llm.py
import json
from dataclasses import dataclass

from mail_organizer.providers.base import Message


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama server is unreachable or the model isn't available."""


@dataclass
class ClassificationResult:
    folder: str | None
    suspicious: bool
    reason: str


class OllamaClient:
    def __init__(self, session, base_url: str = "http://localhost:11434", model: str = "llama3.2:3b"):
        self._session = session
        self._base_url = base_url
        self._model = model

    def check_available(self) -> None:
        try:
            response = self._session.get(f"{self._base_url}/api/tags", timeout=5)
        except Exception as exc:
            raise OllamaUnavailableError(
                f"Ollama não está acessível em {self._base_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise OllamaUnavailableError(f"Ollama retornou status {response.status_code}")

        models = [m.get("name", "") for m in response.json().get("models", [])]
        if not any(self._model in name for name in models):
            raise OllamaUnavailableError(
                f"Modelo {self._model} não encontrado no Ollama (disponíveis: {models})"
            )

    def classify(
        self, message: Message, existing_folders: list[str], heuristic_flags: list[str]
    ) -> ClassificationResult:
        prompt = self._build_prompt(message, existing_folders, heuristic_flags)
        response = self._session.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        data = json.loads(response.json()["response"])
        return ClassificationResult(
            folder=data.get("folder"),
            suspicious=bool(data.get("suspicious", False)),
            reason=data.get("reason", ""),
        )

    def _build_prompt(
        self, message: Message, existing_folders: list[str], heuristic_flags: list[str]
    ) -> str:
        return (
            "Você é um assistente que organiza emails. "
            f"Pastas existentes: {', '.join(existing_folders) if existing_folders else '(nenhuma)'}. "
            f"Sinais técnicos de suspeita já detectados: "
            f"{', '.join(heuristic_flags) if heuristic_flags else 'nenhum'}. "
            f"Remetente: {message.sender}\nAssunto: {message.subject}\n"
            f"Conteúdo: {(message.body_text or '')[:2000]}\n\n"
            "Responda em JSON com as chaves 'folder' (nome de pasta sugerida ou null), "
            "'suspicious' (true/false) e 'reason' (justificativa curta em português)."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/llm.py tests/test_llm.py
git commit -m "feat: add OllamaClient for local LLM classification"
```

---

### Task 6: Optional real-Ollama integration test

**Files:**
- Modify: `tests/test_llm.py`

**Interfaces:**
- None new — this only adds a skippable integration test per the spec's testing requirement.

- [ ] **Step 1: Add the skippable integration test**

```python
# append to tests/test_llm.py
import socket


def _ollama_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 11434), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not running locally — skipping integration test")
def test_classify_returns_expected_shape_against_real_ollama():
    import requests

    client = OllamaClient(requests.Session())
    message = _make_message()

    try:
        result = client.classify(message, existing_folders=["INBOX"], heuristic_flags=[])
    except Exception as exc:
        pytest.skip(f"Ollama reachable but classify() failed (model likely not pulled): {exc}")

    assert isinstance(result.folder, (str, type(None)))
    assert isinstance(result.suspicious, bool)
    assert isinstance(result.reason, str)
```

This test verifies only the **shape** of a real response, per the spec ("verificando apenas o formato esperado da proposta") — never asserts on classification quality/content.

- [ ] **Step 2: Run it to confirm it skips cleanly in this environment**

Run: `pytest tests/test_llm.py -v -k real_ollama`
Expected: `SKIPPED (Ollama not running locally — skipping integration test)` — this is the expected, correct result in an environment without Ollama installed.

- [ ] **Step 3: Run the full llm test file to confirm nothing else broke**

Run: `pytest tests/test_llm.py -v`
Expected: 6 passed, 1 skipped

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm.py
git commit -m "test: add optional real-Ollama integration test (skippable)"
```

---

### Task 7: Proposal generation

**Files:**
- Create: `mail_organizer/proposals.py`
- Test: `tests/test_proposals.py`

**Interfaces:**
- Consumes: `mail_organizer.providers.base.Message`, `mail_organizer.heuristics.HeuristicResult`, `mail_organizer.llm.ClassificationResult` (all existing).
- Produces:
  - `@dataclass Proposal` with fields `message_id: str, action: str, target_folder: str | None, reason: str` (`action` is one of `"move" | "flag_delete" | "keep"`).
  - `build_proposal(message: Message, heuristic_result: HeuristicResult, classification: ClassificationResult) -> Proposal`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proposals.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_proposals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.proposals'`

- [ ] **Step 3: Implement proposals.py**

```python
# mail_organizer/proposals.py
from dataclasses import dataclass

from mail_organizer.heuristics import HeuristicResult
from mail_organizer.llm import ClassificationResult
from mail_organizer.providers.base import Message


@dataclass
class Proposal:
    message_id: str
    action: str  # "move" | "flag_delete" | "keep"
    target_folder: str | None
    reason: str


def build_proposal(
    message: Message, heuristic_result: HeuristicResult, classification: ClassificationResult
) -> Proposal:
    if heuristic_result.is_suspicious or classification.suspicious:
        reasons = list(heuristic_result.flags)
        if classification.suspicious and classification.reason:
            reasons.append(classification.reason)
        return Proposal(
            message_id=message.id,
            action="flag_delete",
            target_folder=None,
            reason="; ".join(reasons) if reasons else "Sinalizado como suspeito pela IA",
        )

    if classification.folder:
        return Proposal(
            message_id=message.id,
            action="move",
            target_folder=classification.folder,
            reason=classification.reason or f"Sugestão de organização: mover para {classification.folder}",
        )

    return Proposal(
        message_id=message.id,
        action="keep",
        target_folder=None,
        reason=classification.reason or "Nenhuma ação sugerida",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_proposals.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/proposals.py tests/test_proposals.py
git commit -m "feat: add proposal-generation logic combining heuristics and LLM"
```

---

### Task 8: Persist proposals and job failures in the database

**Files:**
- Modify: `mail_organizer/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: existing `Database` class (constructor, `_conn`, `_lock`, `init_schema`).
- Produces (new methods on `Database`):
  - `.mark_job_failed(job_id: str, error_message: str) -> None`
  - `.add_proposal(job_id: str, message_id: str, action: str, target_folder: str | None, reason: str) -> None`
  - `.list_proposals(job_id: str) -> list[dict]` (each dict has keys `message_id`, `action`, `target_folder`, `reason`, ordered by insertion)
  - `.get_job(job_id)`'s returned dict now also includes an `error_message` key (via the new `jobs.error_message` column).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_db.py
def test_mark_job_failed_sets_status_and_error_message(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=10)

    db.mark_job_failed("job-1", "Ollama não está rodando")

    job = db.get_job("job-1")
    assert job["status"] == "failed"
    assert job["error_message"] == "Ollama não está rodando"


def test_get_job_error_message_defaults_to_none(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=10)

    job = db.get_job("job-1")

    assert job["error_message"] is None


def test_add_and_list_proposals_roundtrip_in_insertion_order(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=2)

    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")
    db.add_proposal("job-1", "msg-2", "flag_delete", None, "spf_fail")

    proposals = db.list_proposals("job-1")

    assert proposals == [
        {"message_id": "msg-1", "action": "move", "target_folder": "Promotions", "reason": "Newsletter"},
        {"message_id": "msg-2", "action": "flag_delete", "target_folder": None, "reason": "spf_fail"},
    ]


def test_list_proposals_empty_for_job_with_no_proposals(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=0)

    assert db.list_proposals("job-1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "mark_job_failed or proposals"`
Expected: FAIL — `mark_job_failed`/`add_proposal`/`list_proposals` don't exist yet, and `error_message` isn't a column.

- [ ] **Step 3: Modify db.py**

Update the `SCHEMA` constant (add `error_message` to `jobs`, add the new `proposals` table):

```python
# replace the SCHEMA constant in mail_organizer/db.py with:
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    credentials_encrypted BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    total INTEGER NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts (account_id)
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_folder TEXT,
    reason TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);
"""
```

Add these methods to the `Database` class (place them near the other job-related methods):

```python
    def mark_job_failed(self, job_id: str, error_message: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'failed', error_message = ? WHERE job_id = ?",
                (error_message, job_id),
            )
            self._conn.commit()

    def add_proposal(
        self, job_id: str, message_id: str, action: str, target_folder: str | None, reason: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO proposals (job_id, message_id, action, target_folder, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, message_id, action, target_folder, reason),
            )
            self._conn.commit()

    def list_proposals(self, job_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT message_id, action, target_folder, reason FROM proposals WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

`get_job` needs no code change — it already does `dict(row)` on the full `jobs` row via `sqlite3.Row`, so `error_message` appears automatically once the column exists in `SCHEMA`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all db tests, including the 4 new ones)

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `pytest -v`
Expected: all tests pass (baseline 82 + new tests from this plan so far)

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/db.py tests/test_db.py
git commit -m "feat: persist proposals and job failure messages in Database"
```

---

### Task 9: Scan engine orchestration

**Files:**
- Create: `mail_organizer/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes:
  - `mail_organizer.db.Database` — `.mark_job_failed`, `.add_proposal`, `.update_job_progress` (existing, from the connectors plan).
  - `mail_organizer.providers.base.EmailProvider`, `Folder` — `.list_folders() -> list[Folder]` (existing).
  - `mail_organizer.providers.errors.ProviderError` (existing).
  - `mail_organizer.heuristics.analyze_message` (Task 4).
  - `mail_organizer.llm.OllamaClient`, `OllamaUnavailableError` (Task 5).
  - `mail_organizer.proposals.build_proposal` (Task 7).
- Produces: `run_scan(db: Database, provider: EmailProvider, llm_client: OllamaClient, job_id: str, messages: list[Message]) -> None`

  Note: `run_scan` takes an already-fetched `messages` list rather than calling `provider.list_messages(...)` itself. This is a deliberate boundary: the future API-layer plan needs to know `len(messages)` *before* calling `db.create_job(job_id, account_id, total=...)` (per the spec's job-creation flow), so it must call `list_messages` first anyway — passing the result into `run_scan` avoids fetching the mailbox twice and keeps this function trivially testable with a hand-built list of `Message` objects.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scan.py
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


def test_empty_message_list_completes_immediately():
    db = MagicMock()
    provider = MagicMock()
    provider.list_folders.return_value = []
    llm_client = MagicMock()

    run_scan(db, provider, llm_client, "job-1", messages=[])

    db.update_job_progress.assert_called_once_with("job-1", 0, "completed")
    db.add_proposal.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.scan'`

- [ ] **Step 3: Implement scan.py**

```python
# mail_organizer/scan.py
from mail_organizer.db import Database
from mail_organizer.heuristics import analyze_message
from mail_organizer.llm import OllamaClient, OllamaUnavailableError
from mail_organizer.proposals import build_proposal
from mail_organizer.providers.base import EmailProvider, Message
from mail_organizer.providers.errors import ProviderError


def run_scan(
    db: Database,
    provider: EmailProvider,
    llm_client: OllamaClient,
    job_id: str,
    messages: list[Message],
) -> None:
    try:
        llm_client.check_available()
    except OllamaUnavailableError as exc:
        db.mark_job_failed(job_id, str(exc))
        return

    try:
        existing_folders = [folder.name for folder in provider.list_folders()]
    except ProviderError as exc:
        db.mark_job_failed(job_id, f"Falha ao acessar a caixa: {exc}")
        return

    processed = 0
    for message in messages:
        try:
            heuristic_result = analyze_message(message)
            classification = llm_client.classify(message, existing_folders, heuristic_result.flags)
            proposal = build_proposal(message, heuristic_result, classification)
            db.add_proposal(job_id, proposal.message_id, proposal.action, proposal.target_folder, proposal.reason)
        except Exception as exc:
            db.add_proposal(job_id, message.id, "error", None, f"Erro ao analisar: {exc}")
        finally:
            processed += 1
            db.update_job_progress(job_id, processed, "running")

    db.update_job_progress(job_id, processed, "completed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scan.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/scan.py tests/test_scan.py
git commit -m "feat: add scan engine orchestrating heuristics, LLM, and proposal storage"
```

---

### Task 10: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: all tests from this plan plus the connectors-and-persistence plan PASS (0 failures; 1 expected SKIP for the optional Ollama integration test in an environment without Ollama running).

- [ ] **Step 2: Confirm heuristics/proposals modules stay pure (no network/DB imports)**

Run (bash/PowerShell — adapt to your shell):
```
grep -l "import requests\|import sqlite3\|from mail_organizer.db" mail_organizer/heuristics.py mail_organizer/proposals.py
```
Expected: no output (empty) — confirms `heuristics.py` and `proposals.py` stay pure functions per the Global Constraints' testability requirement.

- [ ] **Step 3: Commit (only if step 2 required fixes; otherwise skip)**

```bash
git add -A
git commit -m "chore: verify heuristics/proposals purity and full suite green"
```
