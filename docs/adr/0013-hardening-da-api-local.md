# ADR-0013: Hardening da API local

- **Status:** Aceito
- **Date:** 2026-10-04

## Contexto

A API escuta em `localhost`, mas qualquer página web carregada no navegador do usuário consegue enviar requisições para `localhost` (CSRF e DNS rebinding). A revisão da branch verificou por execução que `POST /proposals/5/approve` com `Origin: http://evil.example`, `Host: evil.example` e `Content-Type: text/plain` retornava 200 e aplicava a proposta: uma requisição cross-site simples bastava para mover ou excluir e-mails.

## Decisão

- **Allowlist de hosts:** `create_app(..., allowed_hosts=[...])` instala o `TrustedHostMiddleware` do Starlette; o `main.py` permite `localhost`, `127.0.0.1` e o hostname de `APP_BASE_URL`. Isso bloqueia DNS rebinding.
- **Cabeçalho obrigatório em requisições mutantes:** qualquer método diferente de GET/HEAD/OPTIONS precisa de `X-Requested-With: mail-organizer`, senão 403. Nenhum cabeçalho CORS é servido, então uma página de outra origem não consegue adicionar o cabeçalho (o preflight falha).
- **Sem CORS:** a API é consumida apenas pelo frontend servido na mesma origem.
- **Validação do `state` do OAuth:** os endpoints `authorize` guardam o `state` gerado; o `callback` exige um `state` conhecido, consome-o (uso único) e responde 400 antes de qualquer troca de código.

## Alternativas consideradas

- **Tokens CSRF / sessões por cookie:** mais pesados para uma API local sem estado e sem login.
- **Apenas allowlist de `Origin`:** falha para clientes que omitem o `Origin`, e não cobre o caso de formulários simples.

## Consequências

- Todo cliente não-GET da API deve enviar `X-Requested-With: mail-organizer` (o `app.js` faz isso no helper compartilhado).
- `allowed_hosts` precisa incluir o host de `APP_BASE_URL`; ao expor a aplicação em outro hostname, ajuste `APP_BASE_URL`.
- O conjunto de `state` pendentes vive em memória: reiniciar o servidor no meio de um fluxo OAuth invalida o `state` e o usuário precisa recomeçar.
