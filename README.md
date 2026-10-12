# Mail Organizer

Intelligent email organization tool with support for Gmail, Outlook, and IMAP. Connects to your email inbox, analyzes messages using technical heuristics and a local LLM, and proposes intelligent organizations — everything without automatic execution, only proposals for your explicit approval.

## Features

- 🔐 **Privacy First** — LLM runs locally via Ollama, no emails sent to external services
- ✅ **Nothing is Automatic** — every action is a proposal until you explicitly approve it
- 📧 **Multi-Provider** — supports Gmail, Outlook/Graph, and any IMAP provider (iCloud, etc.)
- 🧠 **Hybrid Analysis** — combines technical heuristics (SPF/DKIM/DMARC, domain-mismatch detection, suspicious links) with local LLM classification
- 💾 **Protected Credentials** — OAuth tokens and IMAP passwords encrypted at rest
- 🎯 **Action Proposals** — move to folders, flag as suspicious/phishing, or suggest creating server-side rules

## Architecture

### Backend
- **Python 3.12+** with FastAPI + uvicorn
- **SQLite local** for persistence of jobs, proposals, and accounts
- **Four subsystems, all implemented:**
  1. **Connectors** — unified interface for Gmail, Graph (Outlook), IMAP
  2. **Scan Engine** — security heuristics + LLM classification
  3. **API + Frontend** — local REST API + vanilla HTML/JS (connect, scan, review, approve)
  4. **Rule proposals** — suggests server-side rules (Gmail/Graph) for repeated sender → folder patterns

### Frontend
- Vanilla HTML/JS served by FastAPI (no heavy framework)
- Simple flow: connect account → view folders → start scan → review proposals → approve

### Privacy & Security
- LLM via **Ollama** local (default model: `llama3.2:3b`), configurable
- Credentials encrypted with `cryptography.Fernet`
- Everything runs on `localhost`, no external network calls

## Quick Start

### Prerequisites
- Python 3.12 or higher
- Ollama installed with `llama3.2:3b` (or configure your own model)
- For Gmail/Outlook: OAuth app registered (see [ADR-0009](docs/adr/0009-oauth2-with-refresh-token.md))

### Installation
```bash
git clone https://github.com/rafaelaraujolima/mail-organizer.git
cd mail-organizer
pip install -e ".[dev]"
```

### Running Locally
```bash
# Start Ollama in another terminal
ollama serve

# Optional environment variables
export GMAIL_CLIENT_ID="your_client_id"
export GMAIL_CLIENT_SECRET="your_client_secret"
export GRAPH_CLIENT_ID="your_client_id"
export GRAPH_CLIENT_SECRET="your_client_secret"

# Run the API
uvicorn mail_organizer.api.main:app --reload
# Open http://localhost:8000 in your browser
```

### Configuration

All configuration is by environment variable; every variable is optional.

| Variable | Default | Purpose |
|---|---|---|
| `MAIL_ORGANIZER_DATA_DIR` | `~/.mail-organizer` | Directory holding `app.db` and `secret.key` |
| `APP_BASE_URL` | `http://localhost:8000` | Used to build OAuth redirect URIs and the allowed Host list; register the printed redirect URIs with the provider |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | unset | Enable Gmail (both required) |
| `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET` | unset | Enable Outlook / Microsoft Graph (both required) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local LLM endpoint |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model used for classification |
| `RULE_MIN_EMAILS` | `3` | Emails from one sender/domain to one folder before a rule is proposed (integer >= 1) |

Gmail rule creation needs the `gmail.settings.basic` scope; accounts connected before it
was requested must be reconnected. See [ADR-0009](docs/adr/0009-oauth2-with-refresh-token.md)
and [ADR-0013](docs/adr/0013-local-api-hardening.md).

## Architecture Decision Records

All architectural decisions are documented in [docs/adr/](docs/adr/):

- [ADR-0002](docs/adr/0002-python-3-12-minimum.md) — Python 3.12+ minimum version
- [ADR-0003](docs/adr/0003-sqlite-local-database.md) — SQLite local, no ORM, additive migrations
- [ADR-0004](docs/adr/0004-credentials-encryption-with-fernet.md) — Credentials encrypted with Fernet
- [ADR-0005](docs/adr/0005-fastapi-and-uvicorn.md) — FastAPI + uvicorn + BackgroundTasks
- [ADR-0007](docs/adr/0007-local-llm-via-ollama.md) — Local LLM via Ollama
- [ADR-0012](docs/adr/0012-nothing-executes-without-approval.md) — Nothing executes without explicit approval
- [ADR-0013](docs/adr/0013-local-api-hardening.md) — Local API hardening

See all ADRs in [docs/adr/README.md](docs/adr/README.md).

## Project State and Plans

Where the project stands, what is next and the open backlog are in
[docs/STATUS.md](docs/STATUS.md) and [docs/BACKLOG.md](docs/BACKLOG.md). Specs live in
`docs/superpowers/specs/`, implementation plans in `docs/superpowers/plans/`, and the
documentation index is [docs/README.md](docs/README.md).

## Project Structure

```
mail-organizer/
├── mail_organizer/
│   ├── api/              # FastAPI app, routes, dependencies
│   ├── providers/        # Connectors: Gmail, Graph, IMAP
│   ├── heuristics.py     # Security analysis (SPF/DKIM, domain-mismatch, links)
│   ├── llm.py            # Ollama client
│   ├── scan.py           # Scan orchestration (also generates rule proposals)
│   ├── proposals.py      # Proposal logic
│   ├── rules.py          # Pure rule-candidate detection
│   ├── apply.py          # Application of approved proposals (move, delete, create rule)
│   ├── oauth.py          # OAuth2 authorize URLs and code exchange
│   ├── factories.py      # Provider factories (refresh token -> access token)
│   ├── sanitize.py       # HTML sanitization
│   ├── db.py             # SQLite persistence
│   ├── crypto.py         # Credential encryption
│   ├── accounts.py       # Account management
│   └── static/           # Frontend (HTML/JS/CSS)
├── tests/                # pytest test suite
├── docs/
│   ├── STATUS.md         # Current state and next steps (start here)
│   ├── BACKLOG.md        # Open follow-ups and known risks
│   ├── decisions/        # Development rulings log
│   ├── adr/              # Architecture Decision Records
│   └── superpowers/      # Specifications and implementation plans
├── CLAUDE.md             # Instructions loaded automatically by Claude Code
├── pyproject.toml
└── README.md
```

## Testing

```bash
# Run full test suite
pytest -v

# Run specific tests
pytest tests/test_heuristics.py -v
pytest tests/test_scan.py -v
pytest tests/api/test_routes_accounts.py -v

# With coverage
pytest --cov=mail_organizer --cov-report=html
```

**Note:** the integration test with a real Ollama instance is skipped if Ollama is unavailable.

## Development Workflow

### Create feature branch
```bash
git checkout -b feature/your-feature
```

### Implement with TDD
1. Write failing test (`RED`)
2. Minimal implementation (`GREEN`)
3. Refactor if needed (`REFACTOR`)
4. Atomic commit

### Submit PR
```bash
git push origin feature/your-feature
# Open PR on GitHub
```

## Implementation Status

All four planned subsystems are implemented and merged (see
[docs/STATUS.md](docs/STATUS.md) for the phase table). The remaining work is validating
the app against real mail accounts and the open backlog in
[docs/BACKLOG.md](docs/BACKLOG.md); the frontend has not yet been run through the manual
browser checklist.

## License

MIT

## Contact

Rafael Lima (rafael.araujo.lima@outlook.com)
