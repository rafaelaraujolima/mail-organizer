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
- **Three implemented subsystems:**
  1. **Connectors** — unified interface for Gmail, Graph (Outlook), IMAP
  2. **Scan Engine** — security heuristics + LLM classification
  3. **API + Frontend** — in development, local REST API + vanilla HTML/JS

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
- For Gmail/Outlook: OAuth app registered (see [ADR-0009](docs/adr/0009-oauth-manual-com-refresh-token.md))

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

## Architecture Decision Records

All architectural decisions are documented in [docs/adr/](docs/adr/):

- [ADR-0002](docs/adr/0002-python-3-12-ou-superior.md) — Python 3.12+ minimum version
- [ADR-0003](docs/adr/0003-sqlite-como-banco-local.md) — SQLite local, no ORM
- [ADR-0004](docs/adr/0004-criptografia-de-credenciais-com-fernet.md) — Credentials encrypted with Fernet
- [ADR-0005](docs/adr/0005-fastapi-e-uvicorn-para-a-api.md) — FastAPI + uvicorn + BackgroundTasks
- [ADR-0007](docs/adr/0007-llm-local-com-ollama.md) — Local LLM via Ollama
- [ADR-0012](docs/adr/0012-nada-e-executado-sem-aprovacao.md) — Nothing executes without explicit approval

See all 12 ADRs in [docs/adr/README.md](docs/adr/README.md).

## Implementation Plans

Each subsystem has a detailed implementation plan:

1. **Connectors & Persistence** — [docs/superpowers/plans/2026-09-21-connectors-and-persistence.md](docs/superpowers/plans/2026-09-21-connectors-and-persistence.md) ✅ Implemented
2. **Scan Engine** — [docs/superpowers/plans/2026-09-21-scan-engine-heuristics-llm.md](docs/superpowers/plans/2026-09-21-scan-engine-heuristics-llm.md) ✅ Implemented
3. **API + Frontend** — [docs/superpowers/plans/2026-09-22-api-frontend.md](docs/superpowers/plans/2026-09-22-api-frontend.md) 🔄 Ready for implementation

## Project Structure

```
mail-organizer/
├── mail_organizer/
│   ├── api/              # FastAPI app, routes, dependencies
│   ├── providers/        # Connectors: Gmail, Graph, IMAP
│   ├── heuristics.py     # Security analysis (SPF/DKIM, domain-mismatch, links)
│   ├── llm.py            # Ollama client
│   ├── scan.py           # Scan orchestration
│   ├── proposals.py      # Proposal logic
│   ├── apply.py          # Application of approved proposals
│   ├── sanitize.py       # HTML sanitization
│   ├── db.py             # SQLite persistence
│   ├── crypto.py         # Credential encryption
│   ├── accounts.py       # Account management
│   └── static/           # Frontend (HTML/JS/CSS)
├── tests/                # pytest test suite
├── docs/
│   ├── adr/              # Architecture Decision Records
│   └── superpowers/      # Specifications and implementation plans
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

1. ✅ General design specification
2. ✅ Connectors & persistence plan → Implemented
3. ✅ Scan engine plan → Implemented
4. 🔄 API + frontend plan → Ready for implementation (subagent-driven)
5. ⏳ Rules proposal plan (future)

## License

MIT

## Contact

Rafael Lima (rafael.araujo.lima@outlook.com)

---

**Last updated:** 2026-09-26  
**MVP Status:** Connectors and scan engine implemented; API + frontend in planning
