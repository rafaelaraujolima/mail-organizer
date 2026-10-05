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
    from mail_organizer.api.routes_scan import router as scan_router

    app.include_router(accounts_router)
    app.include_router(scan_router)

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
