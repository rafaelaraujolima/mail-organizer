# ADR-0009: OAuth2 Manual Implementation, Storing Only Refresh Token

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Gmail and Graph require OAuth2. The app needs the authorization code flow (redirect + callback) and application credentials registered in Google Cloud Console and Azure AD.

## Decision

- Authorization code flow implemented with `requests` (token exchange at REST endpoints), no dedicated OAuth library. The `google-auth` library (already transitive) is used only to build Gmail client credentials.
- **Only `refresh_token` is stored**, by account. Each use exchanges it for a fresh `access_token`; no expiry tracking.
- `client_id`/`client_secret` come from environment (`GMAIL_CLIENT_ID/SECRET`, `GRAPH_CLIENT_ID/SECRET`); absent, the provider is disabled with clear error (503).
- `redirect_uri` is `APP_BASE_URL` (default `http://localhost:8000`) + callback path and must match exactly what's registered.

## Considered Alternatives

- **`google-auth-oauthlib` and MSAL:** more complete, but two new dependencies for simple flow.
- **Store access token with expiry:** more code and another secret at rest.

## Consequences

- One extra renewal call per provider use (acceptable MVP latency).
- App depends on user registering their own OAuth app.
- **Pending:** `state` param generated in `authorize` but not validated in callback (OAuth CSRF protection). Must be handled before any use outside `localhost`.
