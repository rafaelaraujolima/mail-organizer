# ADR-0004: Credentials Encrypted at Rest with Fernet

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The database stores OAuth `refresh_token` (Gmail/Graph) and IMAP app password. These values grant access to the user's email inbox and cannot be in plaintext.

## Decision

Encrypt each account's credential JSON with **`cryptography.Fernet`** (authenticated symmetric encryption). The key is generated locally on first use and saved to `secret.key` in the data directory, mode `0600`. Credentials are never logged or returned in error messages.

## Considered Alternatives

- **OS keyring:** better isolation, but different behavior and dependencies per OS; deferred.
- **Plaintext in SQLite:** rejected.

## Consequences

- The key lives in the same directory as the database: protects against an isolated `app.db` leak, **not** against full directory access.
- `chmod 0600` has limited effect on Windows; the data directory should live in user-restricted location.
- Losing `secret.key` makes accounts unrecoverable (must reconnect).
