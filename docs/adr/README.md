# Architecture Decision Records

Technology and architecture decisions for Mail Organizer. Format described in [ADR-0001](0001-recording-architecture-decisions.md).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-recording-architecture-decisions.md) | Recording decisions in ADRs | Accepted |
| [0002](0002-python-3-12-minimum.md) | Python 3.12+, tested 3.12–3.14 | Accepted |
| [0003](0003-sqlite-local-database.md) | SQLite as local database | Accepted |
| [0004](0004-credentials-encryption-with-fernet.md) | Credentials encrypted with Fernet | Accepted |
| [0005](0005-fastapi-and-uvicorn.md) | FastAPI + uvicorn + BackgroundTasks | Accepted |
| [0006](0006-vanilla-html-js-frontend.md) | Vanilla HTML/JS frontend | Accepted |
| [0007](0007-local-llm-via-ollama.md) | Local LLM via Ollama | Accepted |
| [0008](0008-emailprovider-interface.md) | EmailProvider interface and connectors | Accepted |
| [0009](0009-oauth2-with-refresh-token.md) | OAuth2 manual, only refresh token | Accepted |
| [0010](0010-html-sanitization-with-bleach.md) | HTML sanitization with bleach | Accepted |
| [0011](0011-testing-strategy-pytest.md) | Testing strategy with pytest | Accepted |
| [0012](0012-nothing-executes-without-approval.md) | Nothing executes without explicit approval | Accepted |
| [0013](0013-local-api-hardening.md) | Local API hardening (host allowlist, required header, OAuth state) | Accepted |
