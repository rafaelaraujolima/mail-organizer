# ADR-0006: Vanilla HTML/JS Frontend Served by FastAPI

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The UI has few screens (connect account, start scan, review proposals) and simple interactions (polling, approve/reject). The spec calls for "simple HTML/JS served by FastAPI itself (no heavy framework)".

## Decision

Static files (`index.html`, `app.js`, `style.css`) in `mail_organizer/static/`, served by `StaticFiles`, using `fetch` and direct DOM manipulation. No framework, no build step, no external CDN dependency.

## Considered Alternatives

- **htmx via CDN:** reduces hand-written JS, adds one frontend dependency for little interactivity.
- **SPA with build (React/Vite):** contradicts spec and adds Node toolchain.

## Consequences

- Zero new frontend dependency; more verbose UI code.
- No automated frontend tests this phase; validation by manual checklist.
- All dynamic DOM content must be escaped (comes from emails and LLM, both untrusted).
