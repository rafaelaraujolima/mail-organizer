# ADR-0003: SQLite as Local Database

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The MVP is local, single-user use via `localhost`. The database stores only: scan job state, generated proposals, connected accounts, and their credentials (encrypted; see ADR-0004). It does not store history of approval/rejection decisions.

## Decision

Use **SQLite** (standard library `sqlite3` module), single file at `MAIL_ORGANIZER_DATA_DIR` (default `~/.mail-organizer/app.db`), no ORM. Schema created by `Database.init_schema()` with `CREATE TABLE IF NOT EXISTS`.

Connection opened with `check_same_thread=False` and writes serialized by `threading.Lock`, because scans run in a FastAPI `BackgroundTasks` thread while the API reads state.

## Considered Alternatives

- **PostgreSQL/MySQL:** requires installing and operating a server for a local app.
- **ORM (SQLAlchemy):** dependency and abstraction layer overkill for 3 simple tables.

## Consequences

- No external server; backup is copying the file.
- **No versioned migrations:** `CREATE TABLE IF NOT EXISTS` does not alter existing tables. A schema change (e.g., new columns in `proposals`) requires deleting the dev `app.db` or introducing a migration mechanism—to be decided in a new ADR before any release to others.
- Multi-user evolution requires revisiting this decision.
