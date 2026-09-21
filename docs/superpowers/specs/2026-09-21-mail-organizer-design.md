# Mail Organizer — Design

Data: 2026-09-21
Status: Aprovado para planejamento de implementação

## Objetivo

Ferramenta/agente que se conecta a uma caixa de email (Gmail, Outlook, Apple/iCloud
ou qualquer provedor IMAP), analisa as mensagens e propõe:

1. Organização em pastas (mover emails para categorias sugeridas por IA).
2. Identificação de emails irrelevantes, spam ou phishing, com proposta de exclusão.
3. Criação de regras nativas na caixa de entrada (Gmail/Outlook) quando um padrão
   repetido de remetente/domínio → pasta é detectado, automatizando organizações
   futuras semelhantes.

**Princípio central: nada é executado automaticamente.** Toda ação (mover, excluir)
é apenas uma *proposta* até o usuário aprovar explicitamente, individualmente ou em
lote por grupo.

Escopo do MVP: uso local, single-user, via interface web rodando em `localhost`.
Uma eventual evolução para produto multi-usuário publicado é um objetivo futuro, não
deste MVP — as decisões abaixo evitam fechar portas para isso, mas não implementam
autenticação multi-tenant, deploy remoto, etc.

## Não-objetivos (fora do MVP)

- Aprendizado com decisões passadas do usuário (cada scan é independente).
- Multi-tenant / publicação como produto para outros usuários.
- Exclusão permanente de emails (delete sempre move para a Lixeira/Trash do provedor).
- Edição de conteúdo de email, resposta, envio.
- Criação de regras via `ImapProvider`: IMAP genérico não tem API padrão de
  filtros/regras do servidor (Sieve existe mas não é universal); a proposta de
  regra fica disponível apenas para contas Gmail e Outlook/Graph.
- Regras com ação de exclusão automática (regra só move para pasta; exclusão
  continua sempre proposta email a email, nunca automatizada por regra).

## Arquitetura

- **Backend:** Python + FastAPI, expõe API REST local.
- **Frontend:** HTML/JS simples servido pelo próprio FastAPI (sem framework pesado).
  Telas: conectar conta → ver pastas atuais → iniciar scan → revisar propostas
  (organizar / excluir) → aprovar/rejeitar.
- **LLM local:** Ollama, modelo leve default (a validar nome exato na implementação,
  ex. `llama3.2:3b`), configurável pelo usuário via config.
- **Persistência:** SQLite local, usado apenas para:
  - Estado dos jobs de scan (em andamento / concluído / falho, progresso).
  - Tokens OAuth (Gmail/Graph) e credenciais IMAP, criptografados em repouso
    (`cryptography.Fernet`, chave gerada localmente no primeiro uso).
  - Config de conexão por conta.
  - **Não** guarda histórico de decisões de aprovação/rejeição (fora de escopo).

## Camada de conectores

Interface comum `EmailProvider`:

```
list_folders()
list_messages(folder, filters)
get_message(id)          # corpo completo + headers
move_message(id, target_folder)
delete_message(id)       # move para Trash/Lixeira do provedor
create_rule(condition, target_folder)   # opcional — ver abaixo
supports_rules()          # bool — indica se o provedor implementa create_rule
```

Implementações:

- `GmailProvider` — Gmail API, OAuth2. Implementa `create_rule` via
  `users.settings.filters` (Gmail Filters API).
- `GraphProvider` — Microsoft Graph API, OAuth2 (cobre Outlook/Hotmail/Office365).
  Implementa `create_rule` via `messageRules` (Graph API).
- `ImapProvider` — IMAP+SMTP genérico. Usado para:
  - Apple/iCloud (preset de host/porta, instruções de senha de app).
  - Qualquer outro provedor IMAP não coberto pelos anteriores.
  - `supports_rules()` retorna `false`; `create_rule` não é implementado
    (ver Não-objetivos). O frontend esconde a opção de criar regra quando
    `supports_rules()` é falso para a conta.

Cada provedor é isolado atrás da interface comum, permitindo testar e adicionar
novos provedores sem alterar o motor de classificação.

## Fluxo de dados

1. **Conectar conta:** usuário escolhe provedor (Gmail / Outlook / Apple / Outro
   IMAP) → fluxo de auth apropriado (OAuth para Gmail/Graph, formulário
   host+usuário+senha-de-app para IMAP) → credenciais salvas criptografadas.
2. **Iniciar scan:** usuário dispara "Escanear caixa" com filtros opcionais (ex.
   só inbox, últimos N dias) para evitar escanear anos de histórico de uma vez.
   Backend cria um `job` (id, status, progresso `0/N`) via `BackgroundTasks`.
3. **Processamento por email, em lote:**
   - Busca metadados + corpo via `EmailProvider`.
   - **Heurísticas técnicas** (rápidas, sem LLM): SPF/DKIM/DMARC do header,
     domínio do remetente vs. domínio alegado, links suspeitos, padrões comuns
     de phishing.
   - **Classificação via LLM local:** sugestão de pasta/categoria com base no
     conteúdo + pastas já existentes na caixa; sinalização de suspeita/
     irrelevância combinando com o resultado das heurísticas.
   - Gera uma **proposta**: mover para pasta X | sinalizar como possível
     phishing/spam com sugestão de exclusão | manter como está — sempre com
     justificativa curta.
   - **Detecção de padrão para regra:** ao final do lote, se `supports_rules()`
     for verdadeiro para a conta e 3+ emails (limiar configurável) do mesmo
     remetente ou domínio receberam a mesma proposta de pasta destino, gera
     também uma **proposta de regra**: "criar regra: emails de
     `<remetente ou domínio>` → mover para pasta X", com justificativa
     informando quantos emails do lote bateram o padrão.
   - Progresso do job atualizado; proposta disponível via polling do frontend.
4. **Revisão pelo usuário:** propostas agrupadas (por pasta sugerida / por
   "possível lixo" / por regra sugerida); aprovação individual ou em lote por
   grupo. Cada proposta de email mostra remetente, assunto, data, preview em
   texto puro e a justificativa da IA. Para ver o corpo HTML completo, o
   usuário clica em "mostrar conteúdo completo" — o HTML passa por
   sanitização (remove `<script>`, bloqueia imagens remotas por padrão, mostra
   URLs em vez de links clicáveis diretos), especialmente relevante para
   emails sinalizados como suspeitos. Uma proposta de regra é revisada e
   aprovada/rejeitada de forma independente das propostas de email do mesmo
   lote — aprovar a regra não aplica retroativamente aos emails já propostos
   individualmente, e vice-versa.
5. **Aplicação:** só ao confirmar, backend chama `move_message`/`delete_message`
   no `EmailProvider` correspondente. Delete = mover para Trash/Lixeira, nunca
   exclusão permanente. Para proposta de regra aprovada, backend chama
   `create_rule` no provedor correspondente (condição: remetente exato ou
   domínio; ação: mover para pasta — sem opção de exclusão automática via
   regra).

## Tratamento de erros

- **Falha de conexão/autenticação:** job marcado `failed` com mensagem clara;
  usuário reconecta a conta sem perder o progresso já processado.
- **Falha do Ollama** (não está rodando / modelo não baixado): detectada no
  início do scan, com orientação clara — não deixa o job pendurado.
- **Falha ao processar um email específico:** não derruba o job inteiro; email
  marcado "erro ao analisar", pulado, reportado ao final para revisão manual.
- **Falha ao aplicar ação aprovada:** reporta sucesso/falha por ação, permite
  retry só das que falharam; nunca reexecuta as que já tiveram sucesso. Vale
  também para `create_rule`: falha ao criar a regra não afeta as propostas de
  email já aplicadas do mesmo lote, e é reportada individualmente com opção
  de retry.
- **Segurança:** tokens/senhas sempre criptografados em repouso; nunca logados
  em texto claro.

## Testes

- **Unitários:** heurísticas de phishing (parsing SPF/DKIM, detecção de domínio
  spoofado, extração de links) e lógica de sanitização de HTML — puras e
  isoladas.
- **Conectores:** testes contra mocks de cada `EmailProvider`, sem bater em
  contas reais, garantindo que a interface comum se comporta igual entre
  Gmail/Graph/IMAP. Inclui teste de que `ImapProvider.supports_rules()`
  retorna `false` e que `GmailProvider`/`GraphProvider` chamam a API de
  filtro/regra correta em `create_rule`.
- **Detecção de padrão para regra:** testes unitários da lógica que agrupa
  propostas do lote por remetente/domínio e decide quando o limiar (3+) é
  atingido — pura e isolada, sem depender de LLM ou provedor real.
- **Classificação LLM:** testes de integração opcionais (skippable se Ollama
  não estiver disponível no ambiente), verificando apenas o formato esperado
  da proposta — qualidade da classificação é validada manualmente pelo usuário
  durante o uso, não em CI.
- **Fluxo ponta a ponta:** checklist de teste manual guiado para o MVP, já que
  envolve contas reais de email — sem mock completo em CI por enquanto.
