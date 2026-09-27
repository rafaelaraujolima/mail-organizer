# ADR-0005: FastAPI + uvicorn, Scans Run as BackgroundTasks

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The product needs a local REST API: connect account, start scan, poll progress, review and apply proposals. A scan can take time (LLM classification per email).

## Decision

- **FastAPI** for routes, **Pydantic** models for request bodies.
- **uvicorn** as ASGI server.
- Scans run as **`BackgroundTasks`** in FastAPI; `POST /scan` creates the job, returns `job_id` immediately, and the frontend polls `GET /jobs/{id}`.
- App assembled by `create_app(...)` factory with injected dependencies, enabling `TestClient` testing without real infrastructure.

## Considered Alternatives

- **Flask/Django:** Django too heavyweight; Flask lacks native validation and dependency injection.
- **Task queue (Celery/RQ):** requires external broker; overkill for single-user.

## Consequences

- Scans run in the same process as the API: restarting mid-scan leaves the job in `running` forever (no resumption). Accepted for MVP.
- Route tests require `httpx` as dev dependency.
