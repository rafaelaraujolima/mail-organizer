# API + Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI REST API and a vanilla HTML/JS frontend that expose the
already-implemented connectors, persistence, and scan-engine subsystems as a working
product: connect an account (OAuth for Gmail/Graph, form for IMAP) → browse folders →
start a scan → review proposals via polling → approve/reject (individually or in
batch) → apply the approved action against the real provider.

**Architecture:** A `create_app(db, provider_factories, ...)` factory
(`mail_organizer/api/app.py`) builds a fully-wired, independently-testable FastAPI
app; three routers (`routes_accounts.py`, `routes_scan.py`, `routes_proposals.py`)
hold the endpoints; four small pure/DI-friendly modules do the real work behind them
(`oauth.py`, `factories.py`, `apply.py`, `sanitize.py`); `mail_organizer/api/main.py`
is the only module that touches real environment variables and the filesystem,
wiring the tested pieces together for `uvicorn` to serve. The frontend is static
HTML/JS/CSS served by FastAPI's `StaticFiles`, calling the REST API with `fetch` —
no new frontend framework, no build step.

**Tech Stack:** Python 3.11+, FastAPI + `uvicorn[standard]` (new), `bleach` (new,
HTML sanitization), `requests` (existing, used directly for OAuth token exchange —
no new OAuth-specific library), `google-auth`/`google-api-python-client` (existing,
already a dependency), `imapclient` (existing), `pytest` + `fastapi.testclient.TestClient`
(needs `httpx`, new dev dependency).

**Spec:** `docs/superpowers/specs/2026-09-22-api-frontend-design.md` (this plan's
spec) and `docs/superpowers/specs/2026-09-21-mail-organizer-design.md` (product spec
it argues from).

## Global Constraints

- **Nada é executado automaticamente.** Every mutating action (move, delete) happens
  only inside `approve`/`batch-approve`, never during scan or on page load.
- **Delete sempre move para Trash/Lixeira do provedor, nunca exclusão permanente** —
  already guaranteed by each `EmailProvider.delete_message` implementation; this plan
  must not add a second delete path that bypasses it.
- **Falha ao aplicar reporta por ação, permite retry só das que falharam, nunca
  reaplica uma proposta já bem-sucedida** — a proposal's `applied_status` becomes
  `'applied'` only on success and is then permanent (409 on re-approve); a failed
  attempt stays `'pending'` (retryable) with `applied_error` set.
- **HTML do corpo do email é sempre sanitizado antes de ir para o frontend:** remove
  `<script>`/`<style>` (tag and content), strips `<img>` entirely (blocks remote image
  loading), converts every `<a href="URL">text</a>` into inert text `text (URL)` —
  never a clickable link.
- **Credenciais (OAuth tokens, senha de app IMAP) nunca aparecem em log ou em uma
  mensagem de erro retornada ao cliente.**
- **`client_id`/`client_secret` de OAuth vêm de variáveis de ambiente**
  (`GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`, `GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`).
  A ausência de qualquer uma delas para um provedor deve produzir um erro claro
  (503 "não configurado"), nunca uma exceção não tratada.
- **`target_folder` é sempre resolvido de nome de exibição para `Folder.id` no
  momento da aplicação**, chamando `provider.list_folders()` de novo — nunca reusa um
  id do momento do scan (pastas podem ter mudado).
- **Sem framework de frontend novo.** HTML/JS puro, `fetch`, sem dependência de build.
- **Contas armazenam apenas `refresh_token`** (Gmail/Graph) ou host/porta/usuário/
  senha (IMAP) — nunca um `access_token` de curta duração; cada uso de um provedor
  OAuth troca o `refresh_token` por um `access_token` novo na hora (mais simples e
  mais seguro do que rastrear expiração, aceitável para um app local single-user).

## Review Focus

- **OAuth callback recebe `error` (usuário negou consentimento) em vez de `code`:**
  deve retornar um erro HTTP claro, nunca uma exceção não tratada tentando ler um
  `code` ausente.
- **Formulário IMAP com credenciais erradas:** deve retornar 400 com mensagem clara
  e **não salvar** a conta — nunca persistir credenciais não verificadas.
- **Aprovar uma proposta cuja pasta de destino não existe mais** (renomeada/apagada
  entre o scan e a revisão): `apply_proposal` deve reportar falha por essa proposta
  específica sem derrubar as outras do lote em `batch-approve`.
- **Reaprovar uma proposta já aplicada** (duplo clique, retry manual): nunca deve
  reexecutar `move_message`/`delete_message` uma segunda vez — 409, sem chamada ao
  provedor.
- **HTML de email adversarial** (link com `javascript:`, atributo `onerror`/`onclick`,
  `<img>` remoto): a sanitização precisa neutralizar todos esses casos, não só o
  `<script>` óbvio citado no spec.

---

### Task 1: Web dependencies + HTML sanitization

**Files:**
- Modify: `pyproject.toml`
- Create: `mail_organizer/sanitize.py`
- Test: `tests/test_sanitize.py`

**Interfaces:**
- Produces: `sanitize_html(html: str | None) -> str`

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml`: add to `dependencies` and `dev`:

```toml
[project]
dependencies = [
    "cryptography>=42.0",
    "google-api-python-client>=2.100",
    "requests>=2.31",
    "imapclient>=3.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "bleach>=6.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sanitize.py
from mail_organizer.sanitize import sanitize_html


def test_removes_script_tag_and_its_content():
    html = "<p>Hello</p><script>alert('xss')</script>"

    assert sanitize_html(html) == "<p>Hello</p>"


def test_removes_style_tag_and_its_content():
    html = "<style>body{display:none}</style><p>Hi</p>"

    assert sanitize_html(html) == "<p>Hi</p>"


def test_strips_img_tag_entirely_to_block_remote_images():
    html = '<p>Look</p><img src="https://evil.com/track.png">'

    assert sanitize_html(html) == "<p>Look</p>"


def test_converts_link_to_visible_text_plus_url():
    html = '<a href="https://evil.example/login">Click here</a>'

    assert sanitize_html(html) == "Click here (https://evil.example/login)"


def test_javascript_uri_link_becomes_inert_text():
    html = '<a href="javascript:alert(1)">Click</a>'

    result = sanitize_html(html)

    assert "<a" not in result
    assert "javascript:alert(1)" in result


def test_strips_event_handler_attributes_from_surviving_tags():
    html = '<div onclick="alert(1)">Hi</div>'

    assert sanitize_html(html) == "<div>Hi</div>"


def test_preserves_allowed_formatting_tags():
    html = "<p>Hello <b>world</b></p>"

    assert sanitize_html(html) == "<p>Hello <b>world</b></p>"


def test_empty_or_none_input_returns_empty_string():
    assert sanitize_html("") == ""
    assert sanitize_html(None) == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_sanitize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.sanitize'`

- [ ] **Step 4: Implement**

```python
# mail_organizer/sanitize.py
import re

import bleach

ALLOWED_TAGS = [
    "p", "br", "b", "i", "strong", "em", "ul", "ol", "li", "blockquote",
    "div", "span", "table", "thead", "tbody", "tr", "th", "td",
]

# html5lib parses <script>/<style> content as raw text, so a bare bleach.clean()
# strip would leave their text content visible on the page (not executable, but
# noise). Remove both tags and their content before the allowlist pass.
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_LINK = re.compile(r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def sanitize_html(html: str | None) -> str:
    if not html:
        return ""

    without_scripts = _SCRIPT_OR_STYLE.sub("", html)
    # Every link becomes inert text plus its raw URL -- nothing in the output is
    # ever clickable, which matters most for messages already flagged suspicious.
    as_text_links = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})", without_scripts)

    return bleach.clean(
        as_text_links,
        tags=ALLOWED_TAGS,
        attributes={},
        strip=True,
        strip_comments=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sanitize.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml mail_organizer/sanitize.py tests/test_sanitize.py
git commit -m "feat: add web dependencies and HTML sanitization for message previews"
```

---

### Task 2: OAuth authorize URLs and token exchange

**Files:**
- Create: `mail_organizer/oauth.py`
- Test: `tests/test_oauth.py`

**Interfaces:**
- Produces:
  - `class OAuthExchangeError(Exception)`
  - `build_gmail_authorize_url(client_id: str, redirect_uri: str, state: str) -> str`
  - `exchange_gmail_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str` (returns `refresh_token`)
  - `build_graph_authorize_url(client_id: str, redirect_uri: str, state: str) -> str`
  - `exchange_graph_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str` (returns `refresh_token`)
  - `GMAIL_TOKEN_URL`, `GRAPH_TOKEN_URL` (module constants, reused by Task 3's token-refresh helper)

`session` is an already-configured `requests.Session`-like object, injected for
testability with `unittest.mock.MagicMock` — same pattern as `GraphProvider`/
`OllamaClient`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_oauth.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.oauth import (
    OAuthExchangeError,
    build_gmail_authorize_url,
    build_graph_authorize_url,
    exchange_gmail_code,
    exchange_graph_code,
)


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


def test_build_gmail_authorize_url_includes_required_params():
    url = build_gmail_authorize_url("client-123", "http://localhost:8000/cb", "state-abc")

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcb" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state-abc" in url


def test_exchange_gmail_code_posts_and_returns_refresh_token():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"refresh_token": "rt-1", "access_token": "at-1"})

    token = exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "auth-code")

    assert token == "rt-1"
    call_kwargs = session.post.call_args.kwargs
    assert call_kwargs["data"]["grant_type"] == "authorization_code"
    assert call_kwargs["data"]["code"] == "auth-code"


def test_exchange_gmail_code_raises_on_non_200():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=400, text="invalid_grant")

    with pytest.raises(OAuthExchangeError):
        exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "bad-code")


def test_exchange_gmail_code_raises_when_refresh_token_missing():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "at-1"})

    with pytest.raises(OAuthExchangeError):
        exchange_gmail_code(session, "cid", "secret", "http://localhost:8000/cb", "auth-code")


def test_build_graph_authorize_url_includes_required_params():
    url = build_graph_authorize_url("client-456", "http://localhost:8000/cb2", "state-xyz")

    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "client_id=client-456" in url
    assert "state=state-xyz" in url
    assert "offline_access" in url


def test_exchange_graph_code_posts_and_returns_refresh_token():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"refresh_token": "rt-2", "access_token": "at-2"})

    token = exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "auth-code")

    assert token == "rt-2"


def test_exchange_graph_code_raises_on_non_200():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=401, text="invalid_client")

    with pytest.raises(OAuthExchangeError):
        exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "bad-code")


def test_exchange_graph_code_raises_when_refresh_token_missing():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "at-2"})

    with pytest.raises(OAuthExchangeError):
        exchange_graph_code(session, "cid", "secret", "http://localhost:8000/cb2", "auth-code")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_oauth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.oauth'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/oauth.py
from urllib.parse import urlencode

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

GRAPH_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_SCOPE = "offline_access Mail.ReadWrite MailboxSettings.ReadWrite"


class OAuthExchangeError(Exception):
    """Raised when a provider's token endpoint rejects the authorization code."""


def build_gmail_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GMAIL_AUTH_URL}?{urlencode(params)}"


def exchange_gmail_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    response = session.post(
        GMAIL_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise OAuthExchangeError(f"Google rejeitou a troca de código: {response.status_code} {response.text}")

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        raise OAuthExchangeError(
            "Google não retornou refresh_token (revogue o acesso em "
            "myaccount.google.com/permissions e tente conectar de novo)"
        )
    return refresh_token


def build_graph_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GRAPH_SCOPE,
        "state": state,
    }
    return f"{GRAPH_AUTH_URL}?{urlencode(params)}"


def exchange_graph_code(session, client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    response = session.post(
        GRAPH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
            "scope": GRAPH_SCOPE,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise OAuthExchangeError(f"Microsoft rejeitou a troca de código: {response.status_code} {response.text}")

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        raise OAuthExchangeError("Microsoft não retornou refresh_token")
    return refresh_token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_oauth.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/oauth.py tests/test_oauth.py
git commit -m "feat: add OAuth2 authorize URLs and code-for-refresh-token exchange"
```

---

### Task 3: Provider factories (Gmail, Graph, IMAP)

**Files:**
- Create: `mail_organizer/factories.py`
- Test: `tests/test_factories.py`

**Interfaces:**
- Consumes: `mail_organizer.oauth.GMAIL_TOKEN_URL`, `GRAPH_TOKEN_URL` (Task 2);
  `mail_organizer.providers.gmail.GmailProvider(service)`,
  `mail_organizer.providers.graph.GraphProvider(session)`,
  `mail_organizer.providers.imap.ImapProvider(client)` (all existing, from the
  connectors plan); `mail_organizer.providers.errors.ProviderAuthError` (existing).
- Produces:
  - `make_gmail_provider_factory(client_id: str, client_secret: str, session=None) -> Callable[[dict], GmailProvider]`
  - `make_graph_provider_factory(client_id: str, client_secret: str, session=None) -> Callable[[dict], GraphProvider]`
  - `imap_provider_factory(credentials: dict) -> ImapProvider`

Every account stores only a `refresh_token` (Gmail/Graph). The two `make_*` functions
close over the app-level `client_id`/`client_secret` (from env vars, read by Task 11's
`main.py`) and an injected `session`, and return the actual per-account factory
function that `AccountService`/`provider_factories` expects: `Callable[[dict], EmailProvider]`.
Each call to that inner factory exchanges the stored `refresh_token` for a fresh
`access_token` before building the provider — no access-token caching or expiry
tracking, per the Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_factories.py
from unittest.mock import MagicMock, patch

import pytest
from imapclient.exceptions import LoginError

from mail_organizer.factories import (
    imap_provider_factory,
    make_gmail_provider_factory,
    make_graph_provider_factory,
)
from mail_organizer.providers.errors import ProviderAuthError
from mail_organizer.providers.gmail import GmailProvider
from mail_organizer.providers.graph import GraphProvider
from mail_organizer.providers.imap import ImapProvider


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


def test_gmail_factory_refreshes_token_and_builds_provider():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "fresh-at"})
    factory = make_gmail_provider_factory("cid", "secret", session=session)

    with patch("mail_organizer.factories.build_google_service") as mock_build, \
         patch("mail_organizer.factories.Credentials") as mock_credentials:
        mock_build.return_value = "the-service"

        provider = factory({"refresh_token": "rt-1"})

    mock_credentials.assert_called_once_with(token="fresh-at")
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_credentials.return_value)
    assert isinstance(provider, GmailProvider)


def test_gmail_factory_raises_provider_auth_error_when_refresh_fails():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=400, text="invalid_grant")
    factory = make_gmail_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "expired"})


def test_graph_factory_refreshes_token_and_builds_provider_with_bearer_header():
    session = MagicMock()
    session.post.return_value = _mock_response(json_body={"access_token": "fresh-graph-at"})
    factory = make_graph_provider_factory("cid", "secret", session=session)

    provider = factory({"refresh_token": "rt-2"})

    assert isinstance(provider, GraphProvider)
    assert provider._session.headers["Authorization"] == "Bearer fresh-graph-at"


def test_graph_factory_raises_provider_auth_error_when_refresh_fails():
    session = MagicMock()
    session.post.return_value = _mock_response(status_code=401, text="invalid_client")
    factory = make_graph_provider_factory("cid", "secret", session=session)

    with pytest.raises(ProviderAuthError):
        factory({"refresh_token": "expired"})


def test_imap_provider_factory_logs_in_and_builds_provider():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_client = MagicMock()
        mock_imap_cls.return_value = mock_client

        provider = imap_provider_factory(
            {"host": "imap.example.com", "port": 993, "username": "a@example.com", "password": "app-pw"}
        )

    mock_imap_cls.assert_called_once_with("imap.example.com", port=993, ssl=True)
    mock_client.login.assert_called_once_with("a@example.com", "app-pw")
    assert isinstance(provider, ImapProvider)


def test_imap_provider_factory_raises_provider_auth_error_on_bad_login():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_client = MagicMock()
        mock_client.login.side_effect = LoginError("bad credentials")
        mock_imap_cls.return_value = mock_client

        with pytest.raises(ProviderAuthError):
            imap_provider_factory(
                {"host": "imap.example.com", "port": 993, "username": "a@example.com", "password": "wrong"}
            )


def test_imap_provider_factory_defaults_port_to_993():
    with patch("mail_organizer.factories.imapclient.IMAPClient") as mock_imap_cls:
        mock_imap_cls.return_value = MagicMock()

        imap_provider_factory({"host": "imap.example.com", "username": "a@example.com", "password": "pw"})

    mock_imap_cls.assert_called_once_with("imap.example.com", port=993, ssl=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_factories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.factories'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/factories.py
import imapclient
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from imapclient.exceptions import LoginError

from mail_organizer.oauth import GMAIL_TOKEN_URL, GRAPH_TOKEN_URL
from mail_organizer.providers.errors import ProviderAuthError
from mail_organizer.providers.gmail import GmailProvider
from mail_organizer.providers.graph import GraphProvider
from mail_organizer.providers.imap import ImapProvider


def _refresh_access_token(session, token_url: str, client_id: str, client_secret: str, refresh_token: str) -> str:
    response = session.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise ProviderAuthError(f"Falha ao renovar token de acesso: {response.status_code} {response.text}")
    return response.json()["access_token"]


def make_gmail_provider_factory(client_id: str, client_secret: str, session=None):
    session = session or requests.Session()

    def factory(credentials: dict) -> GmailProvider:
        access_token = _refresh_access_token(
            session, GMAIL_TOKEN_URL, client_id, client_secret, credentials["refresh_token"]
        )
        service = build_google_service("gmail", "v1", credentials=Credentials(token=access_token))
        return GmailProvider(service)

    return factory


def make_graph_provider_factory(client_id: str, client_secret: str, session=None):
    refresh_session = session or requests.Session()

    def factory(credentials: dict) -> GraphProvider:
        access_token = _refresh_access_token(
            refresh_session, GRAPH_TOKEN_URL, client_id, client_secret, credentials["refresh_token"]
        )
        provider_session = requests.Session()
        provider_session.headers["Authorization"] = f"Bearer {access_token}"
        return GraphProvider(provider_session)

    return factory


def imap_provider_factory(credentials: dict) -> ImapProvider:
    client = imapclient.IMAPClient(credentials["host"], port=credentials.get("port", 993), ssl=True)
    try:
        client.login(credentials["username"], credentials["password"])
    except LoginError as exc:
        raise ProviderAuthError(f"Falha ao autenticar IMAP: {exc}") from exc
    return ImapProvider(client)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_factories.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/factories.py tests/test_factories.py
git commit -m "feat: add provider factories that refresh OAuth tokens and build IMAP sessions"
```

---

### Task 4: Persist proposal id and applied status in the database

**Files:**
- Modify: `mail_organizer/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: existing `Database` class.
- Produces (new/changed methods on `Database`):
  - `.list_proposals(job_id)` — now also returns `id`, `applied_status`, `applied_error` per row.
  - `.get_proposal(proposal_id: int) -> dict | None` — one proposal, including `job_id`.
  - `.mark_proposal_applied(proposal_id: int, status: str, error: str | None = None) -> None`

New proposals default to `applied_status = 'pending'`. Valid values used by later
tasks: `'pending'` (not yet applied, or applied and failed — retryable), `'applied'`
(succeeded, permanent), `'rejected'` (user rejected, terminal).

- [ ] **Step 1: Write the failing tests**

First, find and update the existing round-trip test in `tests/test_db.py` (it currently
asserts full-dict equality against `list_proposals`'s old 4-field shape):

```python
# replace the existing test_add_and_list_proposals_roundtrip_in_insertion_order with:
def test_add_and_list_proposals_roundtrip_in_insertion_order(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=2)

    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")
    db.add_proposal("job-1", "msg-2", "flag_delete", None, "spf_fail")

    proposals = db.list_proposals("job-1")

    assert proposals == [
        {
            "id": 1, "message_id": "msg-1", "action": "move", "target_folder": "Promotions",
            "reason": "Newsletter", "applied_status": "pending", "applied_error": None,
        },
        {
            "id": 2, "message_id": "msg-2", "action": "flag_delete", "target_folder": None,
            "reason": "spf_fail", "applied_status": "pending", "applied_error": None,
        },
    ]
```

Then append new tests:

```python
# append to tests/test_db.py
def test_get_proposal_returns_full_row_including_job_id(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=1)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")

    proposal = db.get_proposal(1)

    assert proposal == {
        "id": 1, "job_id": "job-1", "message_id": "msg-1", "action": "move",
        "target_folder": "Promotions", "reason": "Newsletter",
        "applied_status": "pending", "applied_error": None,
    }


def test_get_proposal_returns_none_for_missing_id(db):
    assert db.get_proposal(999) is None


def test_mark_proposal_applied_sets_status_and_error(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=1)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")

    db.mark_proposal_applied(1, "applied")

    assert db.get_proposal(1)["applied_status"] == "applied"
    assert db.get_proposal(1)["applied_error"] is None


def test_mark_proposal_applied_records_failure_and_stays_retryable(db):
    db.save_account("acc-1", "gmail", "rafael@gmail.com", {"refresh_token": "abc123"})
    db.create_job("job-1", "acc-1", total=1)
    db.add_proposal("job-1", "msg-1", "move", "Promotions", "Newsletter")

    db.mark_proposal_applied(1, "pending", "Pasta não existe mais")

    proposal = db.get_proposal(1)
    assert proposal["applied_status"] == "pending"
    assert proposal["applied_error"] == "Pasta não existe mais"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "proposal"`
Expected: FAIL — the round-trip test fails on the new expected shape; `get_proposal`/`mark_proposal_applied` don't exist yet.

- [ ] **Step 3: Modify db.py**

Update the `SCHEMA` constant's `proposals` table:

```python
# in mail_organizer/db.py, replace the proposals table definition with:
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_folder TEXT,
    reason TEXT NOT NULL,
    applied_status TEXT NOT NULL DEFAULT 'pending',
    applied_error TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);
```

Replace `list_proposals` and add the two new methods:

```python
    def list_proposals(self, job_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, message_id, action, target_folder, reason, applied_status, applied_error
            FROM proposals WHERE job_id = ? ORDER BY id
            """,
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_proposal(self, proposal_id: int) -> dict | None:
        row = self._conn.execute(
            """
            SELECT id, job_id, message_id, action, target_folder, reason, applied_status, applied_error
            FROM proposals WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()
        return dict(row) if row else None

    def mark_proposal_applied(self, proposal_id: int, status: str, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE proposals SET applied_status = ?, applied_error = ? WHERE id = ?",
                (status, error, proposal_id),
            )
            self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all db tests, including the 3 new ones)

- [ ] **Step 5: Update the scan integration test that pins the old shape**

`tests/test_scan.py::test_run_scan_integrates_with_a_real_database` asserts full-dict
equality against `list_proposals`'s old 4-field shape and will fail after this
task's schema change. Replace its assertion on `proposals[0]`:

```python
        assert proposals[0] == {
            "message_id": "msg-1", "action": "move", "target_folder": "Promotions", "reason": "Newsletter"
        }
```

with:

```python
        assert proposals[0] == {
            "id": 1, "message_id": "msg-1", "action": "move", "target_folder": "Promotions",
            "reason": "Newsletter", "applied_status": "pending", "applied_error": None,
        }
```

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/db.py tests/test_db.py
git commit -m "feat: track proposal id and applied status in the database"
```

---

### Task 5: Apply an approved proposal against a provider

**Files:**
- Create: `mail_organizer/apply.py`
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: `mail_organizer.providers.base.EmailProvider`, `Folder` (existing);
  `mail_organizer.providers.errors.ProviderError` (existing). Takes a proposal as a
  plain `dict` (the shape `Database.get_proposal`/`list_proposals` return), not the
  scan-time `Proposal` dataclass — keeps this module decoupled from `proposals.py`.
- Produces:
  - `@dataclass ApplyResult` with fields `success: bool, message: str`
  - `apply_proposal(provider: EmailProvider, proposal: dict) -> ApplyResult`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_apply.py
from unittest.mock import MagicMock

from mail_organizer.apply import ApplyResult, apply_proposal
from mail_organizer.providers.base import Folder
from mail_organizer.providers.errors import ProviderError


def _proposal(**overrides) -> dict:
    defaults = dict(id=1, job_id="job-1", message_id="msg-1", action="move", target_folder="Promotions", reason="r")
    defaults.update(overrides)
    return defaults


def test_apply_move_resolves_folder_name_to_id_and_calls_move_message():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX"), Folder(id="Label_7", name="Promotions")]

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result == ApplyResult(success=True, message="Movido para Promotions")
    provider.move_message.assert_called_once_with("msg-1", "Label_7")


def test_apply_move_fails_clearly_when_folder_name_not_found():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="INBOX", name="INBOX")]

    result = apply_proposal(provider, _proposal(action="move", target_folder="Ghost Folder"))

    assert result.success is False
    assert "Ghost Folder" in result.message
    provider.move_message.assert_not_called()


def test_apply_move_fails_when_list_folders_raises_provider_error():
    provider = MagicMock()
    provider.list_folders.side_effect = ProviderError("auth expired")

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result.success is False
    assert "auth expired" in result.message


def test_apply_move_fails_when_move_message_raises_provider_error():
    provider = MagicMock()
    provider.list_folders.return_value = [Folder(id="Label_7", name="Promotions")]
    provider.move_message.side_effect = ProviderError("rate limited")

    result = apply_proposal(provider, _proposal(action="move", target_folder="Promotions"))

    assert result.success is False
    assert "rate limited" in result.message


def test_apply_flag_delete_calls_delete_message():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="flag_delete", target_folder=None))

    assert result == ApplyResult(success=True, message="Movido para a Lixeira")
    provider.delete_message.assert_called_once_with("msg-1")


def test_apply_flag_delete_fails_when_delete_message_raises():
    provider = MagicMock()
    provider.delete_message.side_effect = ProviderError("not found")

    result = apply_proposal(provider, _proposal(action="flag_delete", target_folder=None))

    assert result.success is False
    assert "not found" in result.message


def test_apply_keep_is_a_noop():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="keep", target_folder=None))

    assert result.success is True
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()


def test_apply_error_action_is_a_noop():
    provider = MagicMock()

    result = apply_proposal(provider, _proposal(action="error", target_folder=None))

    assert result.success is True
    provider.move_message.assert_not_called()
    provider.delete_message.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_apply.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.apply'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/apply.py
from dataclasses import dataclass

from mail_organizer.providers.base import EmailProvider
from mail_organizer.providers.errors import ProviderError


@dataclass
class ApplyResult:
    success: bool
    message: str


def apply_proposal(provider: EmailProvider, proposal: dict) -> ApplyResult:
    action = proposal["action"]

    if action == "move":
        target_name = proposal["target_folder"]
        try:
            folders = provider.list_folders()
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao listar pastas: {exc}")

        matching = [f for f in folders if f.name == target_name]
        if not matching:
            return ApplyResult(success=False, message=f"Pasta '{target_name}' não existe mais na caixa")

        try:
            provider.move_message(proposal["message_id"], matching[0].id)
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao mover mensagem: {exc}")
        return ApplyResult(success=True, message=f"Movido para {target_name}")

    if action == "flag_delete":
        try:
            provider.delete_message(proposal["message_id"])
        except ProviderError as exc:
            return ApplyResult(success=False, message=f"Falha ao excluir mensagem: {exc}")
        return ApplyResult(success=True, message="Movido para a Lixeira")

    # "keep" and "error" proposals require no provider call.
    return ApplyResult(success=True, message="Nenhuma ação necessária")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_apply.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/apply.py tests/test_apply.py
git commit -m "feat: add apply_proposal to resolve folder names and execute the provider action"
```

---

### Task 6: FastAPI app skeleton and account endpoints

**Files:**
- Create: `mail_organizer/api/__init__.py`
- Create: `mail_organizer/api/app.py`
- Create: `mail_organizer/api/deps.py`
- Create: `mail_organizer/api/routes_accounts.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Test: `tests/api/test_routes_accounts.py`

**Interfaces:**
- Consumes: `mail_organizer.accounts.AccountService` (existing);
  `mail_organizer.db.Database` (existing); `mail_organizer.factories.imap_provider_factory`
  (Task 3); `mail_organizer.providers.errors.ProviderError`, `ProviderAuthError` (existing).
- Produces:
  - `create_app(db, provider_factories, *, oauth_config=None, ollama_base_url="http://localhost:11434", ollama_model="llama3.2:3b", static_dir=None) -> FastAPI`
  - `get_db(request) -> Database`, `get_account_service(request) -> AccountService` (FastAPI dependencies)
  - Router mounted at no prefix, paths under `/accounts`: this task implements
    `POST /accounts/imap`, `GET /accounts`, `GET /accounts/{account_id}/folders`.
    (`/accounts/gmail|graph/authorize|callback` come in Task 7, added to the same
    router file.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/__init__.py
```

```python
# tests/api/conftest.py
import pytest
from fastapi.testclient import TestClient

from mail_organizer.api.app import create_app
from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database


@pytest.fixture
def db(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")
    database = Database(tmp_path / "app.db", key)
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def provider_factories():
    """Override in a test module to inject fakes for specific providers."""
    return {}


@pytest.fixture
def app(db, provider_factories):
    return create_app(db, provider_factories)


@pytest.fixture
def client(app):
    return TestClient(app)
```

```python
# tests/api/test_routes_accounts.py
import pytest

from mail_organizer.providers.base import EmailProvider, Folder
from mail_organizer.providers.errors import ProviderError


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials

    def list_folders(self):
        return [Folder(id="INBOX", name="INBOX"), Folder(id="Label_7", name="Promotions")]

    def list_messages(self, folder, filters):
        return []

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


class _FailingFolderProvider(_FakeProvider):
    def list_folders(self):
        raise ProviderError("token expired")


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingFolderProvider}


def test_connect_imap_verifies_credentials_and_persists_account(client, monkeypatch):
    monkeypatch.setattr(
        "mail_organizer.api.routes_accounts.imap_provider_factory",
        lambda credentials: _FakeProvider(credentials),
    )

    response = client.post(
        "/accounts/imap",
        json={"display_name": "iCloud", "host": "imap.mail.me.com", "port": 993, "username": "a@icloud.com", "password": "app-pw"},
    )

    assert response.status_code == 201
    account_id = response.json()["account_id"]
    accounts = client.get("/accounts").json()
    assert any(a["account_id"] == account_id and a["provider"] == "imap" for a in accounts)


def test_connect_imap_rejects_bad_credentials_without_saving(client, monkeypatch):
    def _raise(credentials):
        raise ProviderError("login failed")

    monkeypatch.setattr("mail_organizer.api.routes_accounts.imap_provider_factory", _raise)

    response = client.post(
        "/accounts/imap",
        json={"display_name": "iCloud", "host": "imap.mail.me.com", "port": 993, "username": "a@icloud.com", "password": "wrong"},
    )

    assert response.status_code == 400
    assert client.get("/accounts").json() == []


def test_list_folders_returns_provider_folders(client, db):
    db.save_account("acc-1", "fake", "x", {})

    response = client.get("/accounts/acc-1/folders")

    assert response.status_code == 200
    assert response.json() == [{"id": "INBOX", "name": "INBOX"}, {"id": "Label_7", "name": "Promotions"}]


def test_list_folders_returns_404_for_unknown_account(client):
    response = client.get("/accounts/does-not-exist/folders")

    assert response.status_code == 404


def test_list_folders_returns_502_on_provider_error(client, db):
    db.save_account("acc-1", "failing", "x", {})

    response = client.get("/accounts/acc-1/folders")

    assert response.status_code == 502
    assert "token expired" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_routes_accounts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.api'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/api/__init__.py
```

```python
# mail_organizer/api/deps.py
from fastapi import Request

from mail_organizer.accounts import AccountService
from mail_organizer.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_account_service(request: Request) -> AccountService:
    return request.app.state.account_service
```

```python
# mail_organizer/api/routes_accounts.py
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service
from mail_organizer.factories import imap_provider_factory
from mail_organizer.providers.errors import ProviderError

router = APIRouter(prefix="/accounts", tags=["accounts"])


class ImapConnectRequest(BaseModel):
    display_name: str
    host: str
    port: int = 993
    username: str
    password: str


@router.post("/imap", status_code=201)
def connect_imap(
    body: ImapConnectRequest, service: AccountService = Depends(get_account_service)
) -> dict:
    credentials = {
        "host": body.host, "port": body.port, "username": body.username, "password": body.password,
    }
    try:
        imap_provider_factory(credentials)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível conectar: {exc}")

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "imap", body.display_name, credentials)
    return {"account_id": account_id}


@router.get("")
def list_accounts(service: AccountService = Depends(get_account_service)) -> list[dict]:
    return service.list_accounts()


@router.get("/{account_id}/folders")
def list_folders(account_id: str, service: AccountService = Depends(get_account_service)) -> list[dict]:
    try:
        provider = service.get_provider(account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    try:
        folders = provider.list_folders()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a caixa: {exc}")

    return [{"id": f.id, "name": f.name} for f in folders]
```

```python
# mail_organizer/api/app.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mail_organizer.accounts import AccountService
from mail_organizer.db import Database


def create_app(
    db: Database,
    provider_factories: dict,
    *,
    oauth_config: dict | None = None,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2:3b",
    static_dir=None,
) -> FastAPI:
    app = FastAPI(title="Mail Organizer")
    app.state.db = db
    app.state.account_service = AccountService(db, provider_factories)
    app.state.oauth_config = oauth_config or {}
    app.state.ollama_base_url = ollama_base_url
    app.state.ollama_model = ollama_model

    from mail_organizer.api.routes_accounts import router as accounts_router

    app.include_router(accounts_router)

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
```

Note: `routes_scan.py` and `routes_proposals.py` (Tasks 8-9) will each add their own
`app.include_router(...)` line to `create_app` when they're implemented — this task's
`create_app` only wires the accounts router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_routes_accounts.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/api/__init__.py mail_organizer/api/app.py mail_organizer/api/deps.py \
        mail_organizer/api/routes_accounts.py tests/api/__init__.py tests/api/conftest.py \
        tests/api/test_routes_accounts.py
git commit -m "feat: add FastAPI app skeleton and account/folder endpoints"
```

---

### Task 7: OAuth authorize and callback routes

**Files:**
- Modify: `mail_organizer/api/routes_accounts.py`
- Test: `tests/api/test_routes_accounts_oauth.py`

**Interfaces:**
- Consumes: `mail_organizer.oauth.build_gmail_authorize_url`, `exchange_gmail_code`,
  `build_graph_authorize_url`, `exchange_graph_code`, `OAuthExchangeError` (Task 2).
- Produces: `GET /accounts/gmail/authorize`, `GET /accounts/gmail/callback`,
  `GET /accounts/graph/authorize`, `GET /accounts/graph/callback`.

`request.app.state.oauth_config` is a dict keyed by `"gmail"`/`"graph"`, each value
`{"client_id": str, "client_secret": str, "redirect_uri": str, "session": <requests.Session-like>}`
(built by `main.py` in Task 11; tests inject a `MagicMock` session directly).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_routes_accounts_oauth.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.api.app import create_app
from fastapi.testclient import TestClient


def _mock_response(status_code=200, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


@pytest.fixture
def oauth_session():
    return MagicMock()


@pytest.fixture
def client(db, oauth_session):
    app = create_app(
        db,
        provider_factories={},
        oauth_config={
            "gmail": {"client_id": "gcid", "client_secret": "gsecret", "redirect_uri": "http://x/accounts/gmail/callback", "session": oauth_session},
        },
    )
    return TestClient(app, follow_redirects=False)


def test_gmail_authorize_redirects_to_google_with_client_id(client):
    response = client.get("/accounts/gmail/authorize")

    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]
    assert "client_id=gcid" in response.headers["location"]


def test_graph_authorize_returns_503_when_not_configured(client):
    response = client.get("/accounts/graph/authorize", follow_redirects=False)

    assert response.status_code == 503


def test_gmail_callback_with_error_param_returns_400(client):
    response = client.get("/accounts/gmail/callback?error=access_denied")

    assert response.status_code == 400


def test_gmail_callback_missing_code_returns_400(client):
    response = client.get("/accounts/gmail/callback")

    assert response.status_code == 400


def test_gmail_callback_success_persists_account(client, oauth_session):
    oauth_session.post.return_value = _mock_response(json_body={"refresh_token": "rt-1"})

    response = client.get("/accounts/gmail/callback?code=auth-code&display_name=My+Gmail")

    assert response.status_code == 200
    account_id = response.json()["account_id"]
    accounts = client.get("/accounts").json()
    assert any(a["account_id"] == account_id and a["provider"] == "gmail" for a in accounts)


def test_gmail_callback_returns_502_when_exchange_fails(client, oauth_session):
    oauth_session.post.return_value = _mock_response(status_code=400, text="invalid_grant")

    response = client.get("/accounts/gmail/callback?code=bad-code")

    assert response.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_routes_accounts_oauth.py -v`
Expected: FAIL with 404s (routes don't exist yet)

- [ ] **Step 3: Implement**

Add to `mail_organizer/api/routes_accounts.py` (keep the existing imports and routes
from Task 6, add these):

```python
# add imports at the top of mail_organizer/api/routes_accounts.py
import secrets

from fastapi import Request
from fastapi.responses import RedirectResponse

from mail_organizer.oauth import (
    OAuthExchangeError,
    build_gmail_authorize_url,
    build_graph_authorize_url,
    exchange_gmail_code,
    exchange_graph_code,
)


# add below the existing routes in the same file
def _oauth_config(request: Request, provider: str) -> dict:
    config = request.app.state.oauth_config.get(provider)
    if not config or not config.get("client_id") or not config.get("client_secret"):
        raise HTTPException(
            status_code=503,
            detail=f"OAuth para {provider} não configurado (defina as variáveis de ambiente correspondentes)",
        )
    return config


@router.get("/gmail/authorize")
def gmail_authorize(request: Request):
    config = _oauth_config(request, "gmail")
    state = secrets.token_urlsafe(16)
    url = build_gmail_authorize_url(config["client_id"], config["redirect_uri"], state)
    return RedirectResponse(url)


@router.get("/gmail/callback")
def gmail_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    display_name: str = "Gmail",
    service: AccountService = Depends(get_account_service),
) -> dict:
    if error or not code:
        raise HTTPException(status_code=400, detail=f"Autorização Google não concluída: {error or 'código ausente'}")

    config = _oauth_config(request, "gmail")
    try:
        refresh_token = exchange_gmail_code(
            config["session"], config["client_id"], config["client_secret"], config["redirect_uri"], code
        )
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "gmail", display_name, {"refresh_token": refresh_token})
    return {"account_id": account_id}


@router.get("/graph/authorize")
def graph_authorize(request: Request):
    config = _oauth_config(request, "graph")
    state = secrets.token_urlsafe(16)
    url = build_graph_authorize_url(config["client_id"], config["redirect_uri"], state)
    return RedirectResponse(url)


@router.get("/graph/callback")
def graph_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    display_name: str = "Outlook",
    service: AccountService = Depends(get_account_service),
) -> dict:
    if error or not code:
        raise HTTPException(status_code=400, detail=f"Autorização Microsoft não concluída: {error or 'código ausente'}")

    config = _oauth_config(request, "graph")
    try:
        refresh_token = exchange_graph_code(
            config["session"], config["client_id"], config["client_secret"], config["redirect_uri"], code
        )
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    account_id = str(uuid.uuid4())
    service.connect_account(account_id, "graph", display_name, {"refresh_token": refresh_token})
    return {"account_id": account_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_routes_accounts_oauth.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the accounts test file together to confirm nothing regressed**

Run: `pytest tests/api/test_routes_accounts.py tests/api/test_routes_accounts_oauth.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/api/routes_accounts.py tests/api/test_routes_accounts_oauth.py
git commit -m "feat: add OAuth authorize/callback routes for Gmail and Graph"
```

---

### Task 8: Scan and job endpoints

**Files:**
- Create: `mail_organizer/api/routes_scan.py`
- Modify: `mail_organizer/api/app.py`
- Test: `tests/api/test_routes_scan.py`

**Interfaces:**
- Consumes: `mail_organizer.scan.run_scan(db, provider, llm_client, job_id, messages)`
  (existing, from the scan-engine plan); `mail_organizer.llm.OllamaClient` (existing).
- Produces: `POST /scan`, `GET /jobs/{job_id}`, `GET /jobs/{job_id}/proposals`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_routes_scan.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import EmailProvider, Folder, Message
from mail_organizer.providers.errors import ProviderError


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials

    def list_folders(self):
        return [Folder(id="INBOX", name="INBOX")]

    def list_messages(self, folder, filters):
        return [Message(id="msg-1", folder=folder, sender="a@b.com", subject="Hi", date="2026-01-01")]

    def get_message(self, message_id):
        raise NotImplementedError

    def move_message(self, message_id, target_folder):
        pass

    def delete_message(self, message_id):
        pass


class _FailingListMessagesProvider(_FakeProvider):
    def list_messages(self, folder, filters):
        raise ProviderError("mailbox unreachable")


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingListMessagesProvider}


def test_start_scan_returns_404_for_unknown_account(client):
    response = client.post("/scan", json={"account_id": "does-not-exist", "folder": "INBOX", "filters": {}})

    assert response.status_code == 404


def test_start_scan_returns_502_when_listing_messages_fails(client, db):
    db.save_account("acc-1", "failing", "x", {})

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert response.status_code == 502


def test_start_scan_creates_job_and_runs_it_in_the_background(client, db, monkeypatch):
    db.save_account("acc-1", "fake", "x", {})
    fake_ollama = MagicMock()
    fake_ollama.check_available.side_effect = Exception("no Ollama in tests")
    monkeypatch.setattr("mail_organizer.api.routes_scan.OllamaClient", lambda *a, **kw: fake_ollama)

    response = client.post("/scan", json={"account_id": "acc-1", "folder": "INBOX", "filters": {}})

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert response.json()["total"] == 1

    # TestClient runs BackgroundTasks synchronously before returning the response,
    # so run_scan has already executed with our fake (failing) Ollama client.
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"


def test_get_job_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist")

    assert response.status_code == 404


def test_list_job_proposals_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist/proposals")

    assert response.status_code == 404


def test_list_job_proposals_returns_empty_list_for_job_with_no_proposals(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=0)

    response = client.get("/jobs/job-1/proposals")

    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_routes_scan.py -v`
Expected: FAIL — `/scan` and `/jobs/...` routes 404 (not registered yet)

- [ ] **Step 3: Implement**

```python
# mail_organizer/api/routes_scan.py
import uuid

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service, get_db
from mail_organizer.db import Database
from mail_organizer.llm import OllamaClient
from mail_organizer.providers.errors import ProviderError
from mail_organizer.scan import run_scan

router = APIRouter(tags=["scan"])


class ScanRequest(BaseModel):
    account_id: str
    folder: str
    filters: dict = {}


@router.post("/scan", status_code=201)
def start_scan(
    body: ScanRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: AccountService = Depends(get_account_service),
    db: Database = Depends(get_db),
) -> dict:
    try:
        provider = service.get_provider(body.account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    try:
        messages = provider.list_messages(body.folder, body.filters)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao listar mensagens: {exc}")

    job_id = str(uuid.uuid4())
    db.create_job(job_id, body.account_id, total=len(messages))

    llm_client = OllamaClient(
        requests.Session(), base_url=request.app.state.ollama_base_url, model=request.app.state.ollama_model
    )
    background_tasks.add_task(run_scan, db, provider, llm_client, job_id, messages)

    return {"job_id": job_id, "total": len(messages)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Database = Depends(get_db)) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


@router.get("/jobs/{job_id}/proposals")
def list_job_proposals(job_id: str, db: Database = Depends(get_db)) -> list[dict]:
    if db.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return db.list_proposals(job_id)
```

In `mail_organizer/api/app.py`, register the new router (add alongside the existing
`accounts_router` include):

```python
    from mail_organizer.api.routes_accounts import router as accounts_router
    from mail_organizer.api.routes_scan import router as scan_router

    app.include_router(accounts_router)
    app.include_router(scan_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_routes_scan.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/api/routes_scan.py mail_organizer/api/app.py tests/api/test_routes_scan.py
git commit -m "feat: add scan and job-status endpoints"
```

---

### Task 9: Proposal review endpoints (approve/reject/batch/content)

**Files:**
- Create: `mail_organizer/api/routes_proposals.py`
- Modify: `mail_organizer/api/app.py`
- Test: `tests/api/test_routes_proposals.py`

**Interfaces:**
- Consumes: `mail_organizer.apply.apply_proposal` (Task 5);
  `mail_organizer.sanitize.sanitize_html` (Task 1); `Database.get_proposal`,
  `.mark_proposal_applied`, `.get_job` (Task 4 / existing).
- Produces: `POST /proposals/{proposal_id}/approve`, `POST /proposals/{proposal_id}/reject`,
  `POST /proposals/batch-approve`, `GET /jobs/{job_id}/messages/{message_id}/content`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_routes_proposals.py
from unittest.mock import MagicMock

import pytest

from mail_organizer.providers.base import EmailProvider, Folder, Message
from mail_organizer.providers.errors import ProviderError


class _FakeProvider(EmailProvider):
    def __init__(self, credentials):
        self.credentials = credentials
        self.moved = []
        self.deleted = []

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


@pytest.fixture
def provider_factories():
    return {"fake": _FakeProvider, "failing": _FailingMoveProvider}


def _seed_proposal(db, provider_type="fake", action="move", target_folder="Promotions"):
    db.save_account("acc-1", provider_type, "x", {})
    db.create_job("job-1", "acc-1", total=1)
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


def test_reject_marks_proposal_rejected_without_calling_provider(client, db):
    proposal_id = _seed_proposal(db)

    response = client.post(f"/proposals/{proposal_id}/reject")

    assert response.status_code == 200
    assert db.get_proposal(proposal_id)["applied_status"] == "rejected"


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
    # "Ghost" doesn't exist in _FakeProvider.list_folders(), so this one fails to apply;
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


def test_get_message_content_returns_sanitized_html(client, db):
    db.save_account("acc-1", "fake", "x", {})
    db.create_job("job-1", "acc-1", total=1)

    response = client.get("/jobs/job-1/messages/msg-1/content")

    assert response.status_code == 200
    assert response.json() == {"html": "<p>Hi</p>"}


def test_get_message_content_returns_404_for_unknown_job(client):
    response = client.get("/jobs/does-not-exist/messages/msg-1/content")

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_routes_proposals.py -v`
Expected: FAIL — routes 404 (not registered yet)

- [ ] **Step 3: Implement**

```python
# mail_organizer/api/routes_proposals.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mail_organizer.accounts import AccountService
from mail_organizer.api.deps import get_account_service, get_db
from mail_organizer.apply import apply_proposal
from mail_organizer.db import Database
from mail_organizer.sanitize import sanitize_html

router = APIRouter(tags=["proposals"])


def _apply_and_record(db: Database, service: AccountService, proposal: dict) -> dict:
    job = db.get_job(proposal["job_id"])
    try:
        provider = service.get_provider(job["account_id"])
    except LookupError:
        return {"success": False, "message": "Conta da proposta não encontrada"}

    result = apply_proposal(provider, proposal)
    db.mark_proposal_applied(
        proposal["id"],
        "applied" if result.success else "pending",
        None if result.success else result.message,
    )
    return {"success": result.success, "message": result.message}


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: int, db: Database = Depends(get_db), service: AccountService = Depends(get_account_service)
) -> dict:
    proposal = db.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposta não encontrada")
    if proposal["applied_status"] == "applied":
        raise HTTPException(status_code=409, detail="Proposta já foi aplicada")

    result = _apply_and_record(db, service, proposal)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int, db: Database = Depends(get_db)) -> dict:
    proposal = db.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposta não encontrada")

    db.mark_proposal_applied(proposal_id, "rejected")
    return {"success": True}


class BatchApproveRequest(BaseModel):
    ids: list[int]


@router.post("/proposals/batch-approve")
def batch_approve(
    body: BatchApproveRequest,
    db: Database = Depends(get_db),
    service: AccountService = Depends(get_account_service),
) -> dict:
    results: dict[str, str] = {}
    for proposal_id in body.ids:
        proposal = db.get_proposal(proposal_id)
        if proposal is None:
            results[str(proposal_id)] = "error: proposta não encontrada"
            continue
        if proposal["applied_status"] == "applied":
            results[str(proposal_id)] = "error: já aplicada"
            continue

        outcome = _apply_and_record(db, service, proposal)
        results[str(proposal_id)] = "ok" if outcome["success"] else f"error: {outcome['message']}"

    return results


@router.get("/jobs/{job_id}/messages/{message_id}/content")
def get_message_content(
    job_id: str,
    message_id: str,
    db: Database = Depends(get_db),
    service: AccountService = Depends(get_account_service),
) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    try:
        provider = service.get_provider(job["account_id"])
    except LookupError:
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    message = provider.get_message(message_id)
    return {"html": sanitize_html(message.body_html)}
```

In `mail_organizer/api/app.py`, register the third router:

```python
    from mail_organizer.api.routes_accounts import router as accounts_router
    from mail_organizer.api.routes_scan import router as scan_router
    from mail_organizer.api.routes_proposals import router as proposals_router

    app.include_router(accounts_router)
    app.include_router(scan_router)
    app.include_router(proposals_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_routes_proposals.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add mail_organizer/api/routes_proposals.py mail_organizer/api/app.py tests/api/test_routes_proposals.py
git commit -m "feat: add proposal approve/reject/batch-approve and message content endpoints"
```

---

### Task 10: Frontend (static HTML/JS/CSS)

**Files:**
- Create: `mail_organizer/static/index.html`
- Create: `mail_organizer/static/app.js`
- Create: `mail_organizer/static/style.css`

**Interfaces:**
- Consumes: every endpoint from Tasks 6-9, via `fetch`.
- No automated tests for this task (per the spec's explicit testing scope — frontend
  is covered by a manual checklist, not CI). Steps are write-then-verify-by-reading,
  not red/green.

- [ ] **Step 1: Write `index.html`**

```html
<!-- mail_organizer/static/index.html -->
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Mail Organizer</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <h1>Mail Organizer</h1>

  <section id="accounts-section">
    <h2>Contas conectadas</h2>
    <ul id="account-list"></ul>

    <h3>Conectar Gmail ou Outlook</h3>
    <a id="connect-gmail" href="/accounts/gmail/authorize">Conectar Gmail</a>
    <a id="connect-graph" href="/accounts/graph/authorize">Conectar Outlook</a>

    <h3>Conectar conta IMAP</h3>
    <form id="imap-form">
      <input name="display_name" placeholder="Nome (ex. iCloud)" required>
      <input name="host" placeholder="Host (ex. imap.mail.me.com)" required>
      <input name="port" type="number" value="993" required>
      <input name="username" placeholder="Usuário" required>
      <input name="password" type="password" placeholder="Senha de app" required>
      <button type="submit">Conectar</button>
    </form>
    <p id="imap-error" class="error"></p>
  </section>

  <section id="scan-section" hidden>
    <h2>Escanear caixa</h2>
    <select id="account-select"></select>
    <select id="folder-select"></select>
    <label>Últimos N dias (opcional): <input id="days-filter" type="number"></label>
    <button id="start-scan">Iniciar scan</button>
    <p id="job-status"></p>
  </section>

  <section id="proposals-section" hidden>
    <h2>Propostas</h2>
    <button id="approve-selected">Aprovar selecionadas</button>
    <div id="proposal-list"></div>
  </section>

  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `style.css`**

```css
/* mail_organizer/static/style.css */
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
section { margin-bottom: 2rem; }
.error { color: #b00020; }
.proposal { border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem; }
.proposal.suspicious { border-color: #b00020; background: #fff5f5; }
.proposal .reason { color: #555; font-size: 0.9em; }
.proposal button { margin-right: 0.5rem; }
```

- [ ] **Step 3: Write `app.js`**

```javascript
// mail_organizer/static/app.js
async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadAccounts() {
  const accounts = await fetchJSON("/accounts");
  const list = document.getElementById("account-list");
  const select = document.getElementById("account-select");
  list.innerHTML = "";
  select.innerHTML = "";

  for (const account of accounts) {
    const li = document.createElement("li");
    li.textContent = `${account.display_name} (${account.provider})`;
    list.appendChild(li);

    const option = document.createElement("option");
    option.value = account.account_id;
    option.textContent = account.display_name;
    select.appendChild(option);
  }

  document.getElementById("scan-section").hidden = accounts.length === 0;
  if (accounts.length > 0) {
    await loadFolders(select.value);
  }
}

async function loadFolders(accountId) {
  if (!accountId) return;
  const folders = await fetchJSON(`/accounts/${accountId}/folders`);
  const select = document.getElementById("folder-select");
  select.innerHTML = "";
  for (const folder of folders) {
    const option = document.createElement("option");
    option.value = folder.id;
    option.textContent = folder.name;
    select.appendChild(option);
  }
}

document.getElementById("account-select").addEventListener("change", (event) => {
  loadFolders(event.target.value);
});

document.getElementById("imap-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const errorEl = document.getElementById("imap-error");
  errorEl.textContent = "";

  try {
    await fetchJSON("/accounts/imap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: form.get("display_name"),
        host: form.get("host"),
        port: Number(form.get("port")),
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    event.target.reset();
    await loadAccounts();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

let currentJobId = null;
let pollTimer = null;

document.getElementById("start-scan").addEventListener("click", async () => {
  const accountId = document.getElementById("account-select").value;
  const folder = document.getElementById("folder-select").value;
  const days = document.getElementById("days-filter").value;
  const filters = days ? { days: Number(days) } : {};

  const { job_id } = await fetchJSON("/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId, folder, filters }),
  });

  currentJobId = job_id;
  document.getElementById("proposals-section").hidden = false;
  pollJob();
});

async function pollJob() {
  if (!currentJobId) return;
  const job = await fetchJSON(`/jobs/${currentJobId}`);
  const statusEl = document.getElementById("job-status");
  statusEl.textContent = `Status: ${job.status} (${job.processed}/${job.total})` + (job.error_message ? ` — ${job.error_message}` : "");

  if (job.status === "running") {
    pollTimer = setTimeout(pollJob, 1500);
  } else {
    clearTimeout(pollTimer);
    await loadProposals();
  }
}

async function loadProposals() {
  const proposals = await fetchJSON(`/jobs/${currentJobId}/proposals`);
  const container = document.getElementById("proposal-list");
  container.innerHTML = "";

  for (const proposal of proposals) {
    const div = document.createElement("div");
    div.className = "proposal" + (proposal.action === "flag_delete" ? " suspicious" : "");
    div.innerHTML = `
      <input type="checkbox" class="proposal-checkbox" value="${proposal.id}" ${proposal.applied_status !== "pending" ? "disabled" : ""}>
      <strong>${proposal.action}</strong> ${proposal.target_folder ? "→ " + proposal.target_folder : ""}
      <div class="reason">${proposal.reason}</div>
      <div>Status: ${proposal.applied_status}${proposal.applied_error ? " — " + proposal.applied_error : ""}</div>
      <button class="approve-one" data-id="${proposal.id}" ${proposal.applied_status !== "pending" ? "disabled" : ""}>Aprovar</button>
      <button class="reject-one" data-id="${proposal.id}" ${proposal.applied_status !== "pending" ? "disabled" : ""}>Rejeitar</button>
    `;
    container.appendChild(div);
  }

  container.querySelectorAll(".approve-one").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetchJSON(`/proposals/${btn.dataset.id}/approve`, { method: "POST" }).catch((err) => alert(err.message));
      loadProposals();
    });
  });
  container.querySelectorAll(".reject-one").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetchJSON(`/proposals/${btn.dataset.id}/reject`, { method: "POST" });
      loadProposals();
    });
  });
}

document.getElementById("approve-selected").addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".proposal-checkbox:checked")).map((el) => Number(el.value));
  if (ids.length === 0) return;
  await fetchJSON("/proposals/batch-approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  loadProposals();
});

loadAccounts();
```

- [ ] **Step 4: Verify by reading**

Re-read all three files end to end and confirm: every `fetch` URL and HTTP method
matches an endpoint from Tasks 6-9 exactly (path, method, request/response shape);
no endpoint from those tasks is left with no UI entry point; the IMAP form's field
names match `ImapConnectRequest`'s field names.

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/static/
git commit -m "feat: add vanilla HTML/JS frontend for the connect/scan/review flow"
```

---

### Task 11: Real entrypoint (`main.py`)

**Files:**
- Create: `mail_organizer/api/main.py`
- Test: `tests/api/test_main.py`

**Interfaces:**
- Consumes: `mail_organizer.api.app.create_app` (Task 6); `mail_organizer.factories.imap_provider_factory`,
  `make_gmail_provider_factory`, `make_graph_provider_factory` (Task 3);
  `mail_organizer.crypto.load_or_create_key`, `mail_organizer.db.Database` (existing).
- Produces: `app` (module-level `FastAPI` instance), built entirely from environment
  variables — this is the only module in the codebase that reads `os.environ` or
  touches the real filesystem at import time.

Environment variables: `MAIL_ORGANIZER_DATA_DIR` (default `~/.mail-organizer`),
`APP_BASE_URL` (default `http://localhost:8000`), `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`,
`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` (each pair optional — missing either one
disables that provider, per the Global Constraints), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_main.py
import importlib
import sys

import pytest


@pytest.fixture
def fresh_main_module(tmp_path, monkeypatch):
    """Import mail_organizer.api.main fresh, pointed at a throwaway data dir."""
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    yield module
    module.db.close()
    sys.modules.pop("mail_organizer.api.main", None)


def test_main_builds_a_fastapi_app(fresh_main_module):
    from fastapi import FastAPI

    assert isinstance(fresh_main_module.app, FastAPI)


def test_main_registers_imap_but_not_gmail_when_client_id_missing(fresh_main_module):
    assert "imap" in fresh_main_module.provider_factories
    assert "gmail" not in fresh_main_module.provider_factories


def test_main_registers_gmail_when_client_id_and_secret_present(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAPH_CLIENT_SECRET", raising=False)
    sys.modules.pop("mail_organizer.api.main", None)

    module = importlib.import_module("mail_organizer.api.main")
    try:
        assert "gmail" in module.provider_factories
        assert "gmail" in module.oauth_config
        assert module.oauth_config["gmail"]["redirect_uri"] == "http://localhost:8000/accounts/gmail/callback"
    finally:
        module.db.close()
        sys.modules.pop("mail_organizer.api.main", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mail_organizer.api.main'`

- [ ] **Step 3: Implement**

```python
# mail_organizer/api/main.py
import os
import pathlib

import requests

from mail_organizer.api.app import create_app
from mail_organizer.crypto import load_or_create_key
from mail_organizer.db import Database
from mail_organizer.factories import (
    imap_provider_factory,
    make_gmail_provider_factory,
    make_graph_provider_factory,
)

DATA_DIR = pathlib.Path(os.environ.get("MAIL_ORGANIZER_DATA_DIR", str(pathlib.Path.home() / ".mail-organizer")))
BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")

key = load_or_create_key(DATA_DIR / "secret.key")
db = Database(DATA_DIR / "app.db", key)
db.init_schema()

provider_factories: dict = {"imap": imap_provider_factory}
oauth_config: dict = {}

if os.environ.get("GMAIL_CLIENT_ID") and os.environ.get("GMAIL_CLIENT_SECRET"):
    gmail_client_id = os.environ["GMAIL_CLIENT_ID"]
    gmail_client_secret = os.environ["GMAIL_CLIENT_SECRET"]
    provider_factories["gmail"] = make_gmail_provider_factory(gmail_client_id, gmail_client_secret)
    oauth_config["gmail"] = {
        "client_id": gmail_client_id,
        "client_secret": gmail_client_secret,
        "redirect_uri": f"{BASE_URL}/accounts/gmail/callback",
        "session": requests.Session(),
    }

if os.environ.get("GRAPH_CLIENT_ID") and os.environ.get("GRAPH_CLIENT_SECRET"):
    graph_client_id = os.environ["GRAPH_CLIENT_ID"]
    graph_client_secret = os.environ["GRAPH_CLIENT_SECRET"]
    provider_factories["graph"] = make_graph_provider_factory(graph_client_id, graph_client_secret)
    oauth_config["graph"] = {
        "client_id": graph_client_id,
        "client_secret": graph_client_secret,
        "redirect_uri": f"{BASE_URL}/accounts/graph/callback",
        "session": requests.Session(),
    }

if oauth_config:
    print("OAuth redirect URIs (registre exatamente estes valores no provedor):")
    for provider_name, config in oauth_config.items():
        print(f"  {provider_name}: {config['redirect_uri']}")

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"

app = create_app(
    db,
    provider_factories,
    oauth_config=oauth_config,
    ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
    static_dir=STATIC_DIR,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_main.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mail_organizer/api/main.py tests/api/test_main.py
git commit -m "feat: add real entrypoint wiring env vars into the FastAPI app"
```

---

### Task 12: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: all tests from this plan plus every prior plan PASS (0 failures; 1 expected
SKIP for the optional Ollama integration test from the scan-engine plan, in an
environment without Ollama running).

- [ ] **Step 2: Confirm heuristics/proposals modules still stay pure**

Run (bash/PowerShell — adapt to your shell):
```
grep -l "import requests\|import sqlite3\|from mail_organizer.db" mail_organizer/heuristics.py mail_organizer/proposals.py
```
Expected: no output (empty) — this plan didn't touch either file, so this should
still hold from the scan-engine plan, but re-confirming catches an accidental import
added while wiring things together.

- [ ] **Step 3: Smoke-test the real entrypoint starts and serves the frontend**

```bash
MAIL_ORGANIZER_DATA_DIR=/tmp/mail-organizer-smoke uvicorn mail_organizer.api.main:app --port 8123 &
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8123/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8123/accounts
kill %1
```
Expected: both `curl` calls print `200`. This is a manual smoke check, not part of
the pytest suite — confirms `main.py`'s module-level wiring doesn't crash on import
and the static frontend is actually served, which no automated test in this plan
exercises end-to-end.

- [ ] **Step 4: Commit (only if step 1 or 2 required fixes; otherwise skip)**

```bash
git add -A
git commit -m "chore: verify full suite green and purity constraints hold"
```
