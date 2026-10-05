from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mail_organizer.accounts import AccountService
from mail_organizer.db import Database

# No CORS headers are ever served, so a cross-origin page cannot add this custom
# header (its preflight fails): requiring it on mutating requests blocks CSRF.
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "mail-organizer"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app(
    db: Database,
    provider_factories: dict,
    *,
    oauth_config: dict | None = None,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2:3b",
    static_dir=None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Mail Organizer")
    app.state.db = db
    app.state.account_service = AccountService(db, provider_factories)
    app.state.oauth_config = oauth_config or {}
    app.state.ollama_base_url = ollama_base_url
    app.state.ollama_model = ollama_model
    app.state.oauth_states = set()

    @app.middleware("http")
    async def require_csrf_header(request: Request, call_next):
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
            return JSONResponse({"detail": f"Cabeçalho {CSRF_HEADER} ausente"}, status_code=403)
        return await call_next(request)

    if allowed_hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    from mail_organizer.api.routes_accounts import router as accounts_router
    from mail_organizer.api.routes_scan import router as scan_router
    from mail_organizer.api.routes_proposals import router as proposals_router

    app.include_router(accounts_router)
    app.include_router(scan_router)
    app.include_router(proposals_router)

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
