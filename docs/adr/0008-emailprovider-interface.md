# ADR-0008: EmailProvider Interface and Connectors

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The product works with Gmail, Outlook/Office365, and any IMAP provider (including iCloud), without the classification engine depending on which one is used.

## Decision

A common interface `EmailProvider` (`list_folders`, `list_messages`, `get_message`, `move_message`, `delete_message`, `supports_rules`, `create_rule`) with three implementations:

- **`GmailProvider`** — Gmail API via `google-api-python-client`.
- **`GraphProvider`** — Microsoft Graph via `requests`.
- **`ImapProvider`** — IMAP via `IMAPClient`.

Each provider receives its already-authenticated client/session by dependency injection and translates errors to a common taxonomy (`ProviderError`, `ProviderAuthError`, `ProviderRateLimitError`, `MessageNotFoundError`). `delete_message` always moves to provider Trash, never permanent. `move_message` and `create_rule` receive `Folder.id`, not display name.

## Considered Alternatives

- **IMAP for everything:** Gmail and Outlook require OAuth for IMAP and do not expose server-side rules via IMAP.
- **Unified email library:** none cover Gmail/Graph/IMAP with native rules.

## Consequences

- Adding a provider does not touch the scan engine.
- Rule creation only exists for Gmail and Graph (`supports_rules()` is false on IMAP).
- Folder name and id diverge (Gmail `Label_7` vs `Promotions`); name→id resolution happens at apply time.
