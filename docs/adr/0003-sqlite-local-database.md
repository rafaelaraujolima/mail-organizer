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
- **No migration framework:** `CREATE TABLE IF NOT EXISTS` does not alter existing tables, so `init_schema` additively adds the columns that are missing (`ALTER TABLE ... ADD COLUMN`, always nullable or with a default) and creates new tables. Existing data is kept. A change that cannot be expressed as an additive column (renaming, dropping, changing a type) still needs a new ADR.
- `init_schema` raises `SchemaOutOfDateError` only if an additive `ALTER TABLE` fails (delete or move the file aside in that case).
- Multi-user evolution requires revisiting this decision.
