# ADR-0007: Local LLM via Ollama

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Classification (folder suggestion and suspicion flagging) must read private email content. Sending that content to an external API is a privacy problem for the product.

## Decision

Use **Ollama** running locally (`http://localhost:11434`), default model `llama3.2:3b`, configurable via `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. The client (`OllamaClient`) receives the HTTP session by injection. Ollama and model availability is checked at the start of each scan; failure marks the job `failed` with clear guidance.

## Considered Alternatives

- **Cloud LLM API:** better quality, but sends emails to third parties.
- **Heuristics only, no LLM:** cannot suggest folders by content.

## Consequences

- User must install Ollama and download the model.
- Small model errs: LLM can suggest non-existent folder (scan discards out-of-list names) and email content may try to manipulate the response (prompt injection). Technical heuristics are computed independently of the LLM; nothing executes without approval (ADR-0012).
- Real Ollama tests are optional, skip if unavailable; verify response format only.
