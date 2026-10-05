# ADR-0013: Local API Hardening

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The API listens on `localhost`, but any web page loaded in the user's browser can send requests to `localhost` (CSRF and DNS rebinding attacks). A review of the branch verified by demonstration that `POST /proposals/5/approve` with `Origin: http://evil.example`, `Host: evil.example`, and `Content-Type: text/plain` returned 200 and applied the proposal—a simple cross-site request was enough to move or delete emails.

## Decision

- **Host allowlist:** `create_app(..., allowed_hosts=[...])` installs Starlette's `TrustedHostMiddleware`; `main.py` permits `localhost`, `127.0.0.1`, and the hostname from `APP_BASE_URL`. This blocks DNS rebinding.
- **Required header on mutating requests:** any method other than GET/HEAD/OPTIONS requires `X-Requested-With: mail-organizer`, or 403. No CORS headers are served, so a cross-origin page cannot add the header (preflight fails).
- **No CORS:** the API is consumed only by the frontend served from the same origin.
- **OAuth `state` validation:** `authorize` endpoints store the generated `state`; `callback` requires a known `state`, consumes it (single use), and responds 400 before any code exchange.

## Considered Alternatives

- **CSRF tokens / cookie sessions:** heavier for a local, stateless API without login.
- **`Origin` allowlist only:** fails for clients that omit `Origin`, and does not cover simple form requests.

## Consequences

- Every non-GET API client must send `X-Requested-With: mail-organizer` (the `app.js` does this in the shared helper).
- `allowed_hosts` must include the host from `APP_BASE_URL`; when exposing the application on another hostname, adjust `APP_BASE_URL`.
- The set of pending `state` values lives in memory: restarting the server mid-OAuth flow invalidates the `state`, and the user must restart the flow.
