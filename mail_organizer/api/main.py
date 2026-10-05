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
