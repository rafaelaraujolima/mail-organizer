# API + Frontend — Design

Data: 2026-09-22
Status: Aprovado para planejamento de implementação

Referências: `docs/superpowers/specs/2026-09-21-mail-organizer-design.md` (spec geral do
produto), `docs/superpowers/plans/2026-09-21-connectors-and-persistence.md` e
`docs/superpowers/plans/2026-09-21-scan-engine-heuristics-llm.md` (subsistemas já
implementados e mergeados que este subsistema consome).

## Objetivo

Terceiro dos quatro subsistemas planejados (conectores+persistência e o motor de scan
já estão prontos; a proposta de regras vem depois deste). Expõe o produto por uma API
REST local (FastAPI) e um frontend simples, cobrindo o fluxo completo do MVP: conectar
conta → ver pastas → iniciar scan → revisar propostas (via polling) → aprovar/rejeitar
→ aplicar (mover/excluir de verdade no provedor).

Fora de escopo aqui (fica para o próximo subsistema): detecção de padrão para proposta
de regra e `create_rule`. A API deste subsistema não impede que ele seja adicionado
depois — `run_scan`/`build_proposal` já são chamados como estão, sem alteração.

## Arquitetura

App FastAPI único, montado em `mail_organizer/api/`, com routers por domínio
(`accounts`, `scan`, `proposals`). O frontend é servido como arquivos estáticos pelo
próprio FastAPI (`StaticFiles`), sem build step — HTML/JS puro (`fetch`), sem framework
novo, mantendo a mesma disciplina de dependências mínimas dos subsistemas anteriores.

`mail_organizer/api/main.py` monta a `FastAPI` app: cria o `Database` (path configurável
por env var, default local), o dict de `provider_factories` (gmail/graph/imap →
função que constrói o `EmailProvider` autenticado a partir das credenciais salvas),
instancia `AccountService`, registra os routers e monta `StaticFiles` na raiz.

## Componentes novos

- **`mail_organizer/oauth.py`** — handshake OAuth2 para Gmail e Graph.
  - Gmail: fluxo de autorização via `google-auth-oauthlib` (já complementa a
    dependência existente `google-api-python-client`), escopo
    `https://www.googleapis.com/auth/gmail.modify`.
  - Graph: fluxo de código de autorização OAuth2 padrão implementado com `requests`
    puro (sem nova dependência — Microsoft expõe endpoints OAuth2 REST simples;
    `GraphProvider` já usa `requests` diretamente para a API).
  - `client_id`/`client_secret` lidos de variáveis de ambiente:
    `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`, `GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`.
    Ausência de uma delas desabilita o botão/endpoint correspondente no frontend com
    mensagem clara ("configure GMAIL_CLIENT_ID/SECRET"), em vez de falhar de forma
    obscura.
  - `redirect_uri` construído a partir de uma env var `APP_BASE_URL` (default
    `http://localhost:8000`) + o path do callback (ex.
    `{APP_BASE_URL}/accounts/gmail/callback`) — precisa bater exatamente com o que foi
    registrado no Google Cloud Console / Azure AD, então o valor efetivo é logado uma
    vez na inicialização do servidor para facilitar o registro.
  - Troca código→token; apenas o `refresh_token` é persistido via
    `AccountService.connect_account` (que já criptografa em repouso via `db.py`).
    Nunca se guarda `access_token`: a cada uso de um provedor OAuth, o factory troca o
    `refresh_token` por um `access_token` novo na hora — mais simples e mais seguro que
    rastrear expiração, aceitável para um app local single-user.
  - Nenhuma credencial OAuth é logada. As mensagens de erro de troca de token
    devolvidas ao frontend são construídas por `oauth.py` (status HTTP + corpo de erro
    do provedor, ou uma orientação como "revogue o acesso e reconecte") e nunca contêm
    tokens, `code` ou `client_secret`.

- **`mail_organizer/sanitize.py`** — `sanitize_html(html: str) -> str`, usando
  `bleach` (nova dependência): allowlist restrita de tags (`p`, `br`, `b`, `i`,
  `strong`, `em`, `ul`, `ol`, `li`, `blockquote`, `div`, `span`, `table*`), remove
  `<script>`/`<style>` (tag e conteúdo) e todos os atributos (`on*` handlers, etc.),
  remove `<img>` por inteiro (nenhuma imagem remota chega a ser carregada — mais
  simples e mais robusto que só remover o `src`), e substitui `<a href="URL">texto</a>` pelo texto `texto (URL)`
  em vez de um link clicável — conforme o requisito do spec geral, "especialmente
  relevante para emails sinalizados como suspeitos".

- **`mail_organizer/apply.py`** — `apply_proposal(db, provider, proposal) -> ApplyResult`.
  - Resolve `proposal.target_folder` (nome de exibição, como persistido pelo motor de
    scan) para o `Folder.id` do provedor chamando `provider.list_folders()` de novo no
    momento da aplicação — nunca reutiliza um id armazenado no scan, porque pastas
    podem ter sido renomeadas/removidas entre o scan e a aprovação. Se o nome não for
    encontrado nas pastas atuais, `ApplyResult` reporta falha com mensagem clara (não
    tenta criar a pasta).
  - `action == "move"` → `provider.move_message(message_id, folder_id)`.
  - `action == "flag_delete"` → `provider.delete_message(message_id)` (sempre
    Lixeira/Trash do provedor via a implementação do `EmailProvider`, nunca exclusão
    permanente — já garantido pela camada de conectores).
  - `action in ("keep", "error")` → no-op, marca como aplicado sem chamar o provedor.
  - Falha ao aplicar não derruba as outras aplicações do lote (mesmo padrão de
    isolamento por item que o motor de scan já usa) e é reportada individualmente,
    permitindo retry só da que falhou.

- **`mail_organizer/api/routes_accounts.py`, `routes_scan.py`, `routes_proposals.py`**
  — os routers FastAPI com os endpoints abaixo.

- **Mudanças em `db.py`** (a persistência existente não expõe o suficiente para a API
  referenciar/aplicar uma proposta individual):
  - `proposals` ganha duas colunas: `applied_status TEXT DEFAULT 'pending'` (`pending`
    | `applied` | `rejected`) e `applied_error TEXT` (mensagem da última tentativa de
    aplicação que falhou, para exibir e permitir retry).
  - `list_proposals(job_id)` passa a incluir `id`, `applied_status` e `applied_error`
    nos dicts retornados (aditivo — os testes existentes que fazem comparação de dict
    completo em `tests/test_db.py` precisam ser atualizados para os novos campos,
    mesmo ajuste que `error_message` exigiu no motor de scan).
  - novo `get_proposal(proposal_id) -> dict | None` — uma proposta por id, mesmos
    campos de `list_proposals` mais `job_id` (para resolver `account_id` via
    `get_job(job_id)`).
  - novo `mark_proposal_applied(proposal_id, status, error=None) -> None` — grava o
    resultado de uma tentativa de aplicação; `approve` retorna 409 se
    `applied_status` já for `applied` (idempotência: nunca reaplica uma proposta com
    sucesso anterior, conforme o spec geral).

- **`mail_organizer/static/`** — `index.html`, `app.js`, `style.css`. Três telas em
  uma SPA simples de estado local (sem roteador): conectar conta → escolher pasta e
  iniciar scan → revisar propostas (lista com polling de `GET /jobs/{id}`, agrupada
  por ação sugerida, cada item com preview em texto puro + botão "mostrar conteúdo
  completo" que busca o HTML sanitizado sob demanda).

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/accounts/imap` | Conecta conta IMAP (host, porta, usuário, senha de app) |
| `GET` | `/accounts/gmail/authorize` | Redireciona para o consentimento OAuth do Google |
| `GET` | `/accounts/gmail/callback` | Recebe o `code`, troca por token, salva a conta |
| `GET` | `/accounts/graph/authorize` | Redireciona para o consentimento OAuth da Microsoft |
| `GET` | `/accounts/graph/callback` | Recebe o `code`, troca por token, salva a conta |
| `GET` | `/accounts` | Lista contas conectadas (sem credenciais) |
| `GET` | `/accounts/{id}/folders` | Lista pastas da conta (via `EmailProvider.list_folders`) |
| `POST` | `/scan` | `{account_id, folder, filters}` → cria job, dispara `BackgroundTasks(run_scan, ...)`, retorna `job_id` |
| `GET` | `/jobs/{id}` | Status/progresso do job (para polling) |
| `GET` | `/jobs/{id}/proposals` | Lista propostas do job (agora com `id`, `applied_status`), agrupáveis no frontend por ação/pasta |
| `GET` | `/jobs/{job_id}/messages/{message_id}/content` | Corpo HTML sanitizado (`sanitize_html`) para "mostrar conteúdo completo" — job_id resolve a conta/provider corretos |
| `POST` | `/proposals/{id}/approve` | Aplica a proposta agora (chama `apply_proposal`); 409 se já `applied` |
| `POST` | `/proposals/{id}/reject` | Marca como rejeitada, nenhuma ação no provedor |
| `POST` | `/proposals/batch-approve` | `{ids: [...]}`, aplica cada uma, retorna resultado por id |

Aplicação é síncrona dentro do approve (chama `apply_proposal` na hora e retorna o
resultado) — sem fila separada, dado o volume esperado de um MVP local single-user.

## Tratamento de erros

- **Falha de conexão/autenticação** (ao iniciar scan ou listar pastas): job/requisição
  retorna erro claro; conta permanece salva, usuário reconecta sem perder progresso já
  processado (mesma garantia que `run_scan` já oferece via `mark_job_failed`).
- **Falha do Ollama / falha por email**: já tratado pelo subsistema de scan
  (`run_scan`); este subsistema só expõe `job.status`/`job.error_message` e as
  propostas com `action="error"` como estão.
- **Falha ao aplicar uma proposta aprovada**: `apply_proposal` reporta sucesso/falha
  por ação; endpoint de aprovação individual retorna o erro direto; o batch retorna um
  mapa `{id: "ok" | "error: <mensagem>"}`. Nunca reaplica uma proposta cujo
  `apply_proposal` anterior já teve sucesso (idempotência simples: proposta aprovada
  com sucesso não pode ser reenviada para approve — o endpoint retorna 409 se já
  aplicada).
- **Segurança:** nenhuma credencial (OAuth ou IMAP) é logada; erros retornados ao
  frontend nunca incluem tokens/segredos brutos.

## Testes

- **Rotas:** `fastapi.testclient.TestClient`, com `AccountService`/`Database`/
  provider factories mockados/injetados via `dependency_overrides` — sem bater em
  contas reais.
- **OAuth:** testa a troca código→token mockando a chamada HTTP externa (Google/
  Microsoft) — nunca contra as APIs reais; testa o caminho de `client_id`/`secret`
  ausente retornando o erro claro.
- **`sanitize_html`:** testes unitários puros — remove `<script>`/`<style>`, remove
  `<img>`, converte `<a>` (inclusive `javascript:`) em texto+URL, remove atributos
  de eventos, preserva tags da allowlist.
- **`apply_proposal`:** provider mockado — resolve nome→id corretamente, ambos os
  ramos de ação (move/delete), pasta não encontrada, falha do provedor não derruba
  outras aplicações do lote.
- **Frontend:** sem testes automatizados nesta rodada (fora do padrão de testes do
  projeto até aqui, que cobre só Python); checklist de teste manual guiado, como o
  spec geral já prevê para o fluxo ponta a ponta.
