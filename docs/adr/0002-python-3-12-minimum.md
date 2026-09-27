# ADR-0002: Python 3.12 as Minimum Version, Tested 3.12–3.14

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

`pyproject.toml` declares `requires-python = ">=3.11"`, but all development and tests ran only on 3.14.7. Python 3.11 was never verified. The code uses modern syntax (`str | None`, `list[dict]`), requiring 3.10+.

## Decision

- **Minimum version:** Python 3.12.
- **Supported and tested versions:** 3.12, 3.13, and 3.14.
- Local development using the latest stable available version.

## Considered Alternatives

- **Keep floor at 3.11:** would require verifying 3.11, which exits support October 2027, with no benefit for a local single-user app.
- **Fix to 3.14 only:** locks the project against older Python environments without real benefit.

## Consequences

- `requires-python` must update to `>=3.12`.
- Tests must run on all three versions (CI matrix or local per-version execution).
- Do not use features exclusive to versions above 3.12 without a new ADR.
