# ADR-0010: HTML Sanitization with bleach

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

To review a proposal, the user can view email body HTML, which is untrusted content—especially in messages flagged as phishing. Hand-rolled HTML sanitization is notoriously easy to get wrong (XSS).

## Decision

Use **`bleach`** with a restrictive allowlist of tags (`p`, `br`, `b`, `i`, `strong`, `em`, `ul`, `ol`, `li`, `blockquote`, `div`, `span`, tables) and **no attributes allowed**. Before bleach, strip `<script>`/`<style>` plus content and convert each `<a href="URL">text</a>` to inert text `text (URL)`. `<img>` is not in the list, so no remote images load.

## Considered Alternatives

- **Regex/`html.parser` custom:** high risk of breach.
- **`nh3`:** modern Rust-based alternative; bleach is sufficient and widely used (maintained in maintenance mode).

## Consequences

- New dependency (`bleach`).
- No clickable links in preview: user sees raw URL.
- Emails relying on images/styles look poor—accepted.
- LLM-generated justification text is also untrusted and must be escaped on frontend (see ADR-0006).
