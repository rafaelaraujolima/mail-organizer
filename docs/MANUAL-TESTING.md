# Manual Testing Checklist

Everything the automated suite cannot cover: the browser UI and the real Gmail, Outlook/Graph
and IMAP servers (all provider tests use mocks, ADR-0011). Run this before trusting the app
with a real mailbox, and again after changes to connectors, OAuth, the UI or rule creation.

**Use a throwaway mailbox, never your main account.** The app only moves mail to Trash,
but this is the first contact with real servers.

Record results in the table at the end and commit them. Where a step fails, capture:
the step number, what the UI showed, the time, and the `uvicorn` log lines.

## 0. Preparation

**Ollama**

```powershell
ollama pull llama3.2:3b
ollama serve
```

**Test mailbox content** (send or forward beforehand):

- 4 emails from one newsletter-like sender (above the default rule threshold of 3);
- 3 emails from a second sender on the same domain as another sender;
- 2 phishing-looking emails (shortened link, sender not matching the domain, "verify your account");
- 2 ordinary personal emails;
- 1 heavy HTML email (images, links, ideally a `<script>`).

**Folders:** create at least "Promotions", "Newsletters" and "Test". Without existing
folders the LLM has nowhere to suggest.

**Start the app**

```powershell
$env:MAIL_ORGANIZER_DATA_DIR = "C:\temp\mo-test"
# Gmail / Outlook only (section 5):
$env:GMAIL_CLIENT_ID = "..." ; $env:GMAIL_CLIENT_SECRET = "..."
$env:GRAPH_CLIENT_ID = "..." ; $env:GRAPH_CLIENT_SECRET = "..."
uvicorn mail_organizer.api.main:app --port 8000
```

Open http://localhost:8000. The terminal prints the OAuth redirect URIs to register.

## 1. Connect an IMAP account

| # | Step | Expected |
|---|---|---|
| 1.1 | Submit a **wrong password** | Clear error; the account is **not** listed |
| 1.2 | Submit a **non-existent host** (`naoexiste.invalid`) | Clear error; not saved; page keeps working |
| 1.3 | Submit correct data (iCloud: `imap.mail.me.com`, 993, **app password**) | Account listed; selecting it shows its folders |
| 1.4 | Stop and restart the server | The account is still there |

## 2. Scan

| # | Step | Expected |
|---|---|---|
| 2.1 | Pick account, INBOX, no day filter, start scan | Status `running` with `processed/total`, then `completed` |
| 2.2 | Repeat with day filter = 7 | Smaller total |
| 2.3 | **Stop Ollama**, start a scan | Job `failed` with a clear Ollama message, not stuck |
| 2.4 | Restart Ollama, repeat | Works again |

## 3. Reviewing proposals

| # | Step | Expected |
|---|---|---|
| 3.1 | Look at the groups | Headings "Mover", "Regras sugeridas", "Possível lixo/phishing", "Manter", "Erro"; empty groups hidden |
| 3.2 | Inspect items | Sender, subject, date, snippet and reason readable; no HTML interpreted |
| 3.3 | Phishing-looking emails | Ideally under "Possível lixo/phishing" (misses are LLM quality, note them, not bugs) |
| 3.4 | "Ver conteúdo" on the heavy HTML email | Isolated frame; no remote images; **links shown as text with their URL**; nothing executes |
| 3.5 | Double-click "Ver conteúdo" quickly | Only one frame |

## 4. Approve, reject, batch

| # | Step | Expected |
|---|---|---|
| 4.1 | Approve one "move" proposal | `applied`; the email is in the target folder in the webmail |
| 4.2 | Approve one "possível lixo" | The email is in **Trash** (never permanently deleted) |
| 4.3 | **Double-click** Approve | One action; buttons lock during the call |
| 4.4 | Reject one | `rejected`; mailbox unchanged |
| 4.5 | Select 3 and "Aprovar selecionadas" | Summary "N aplicadas, M com erro"; verify in the mailbox |
| 4.6 | **Provoke a failure:** after the scan, rename a target folder in the webmail, then approve | Error saying the folder no longer exists; proposal stays pending; others in a batch still apply |
| 4.7 | Restore the folder name and approve again | Applies (retry works) |
| 4.8 | Reload and try to re-approve an applied proposal | Controls disabled (API answers 409 if forced) |

## 5. Rule proposals (Gmail and Outlook; IMAP has none)

**Register the OAuth app once**

- **Google:** Cloud Console -> project -> enable Gmail API -> consent screen (add your account as a *test user*) -> "Web application" credential with redirect `http://localhost:8000/accounts/gmail/callback`.
- **Microsoft:** Entra ID -> App registration -> Web, redirect `http://localhost:8000/accounts/graph/callback` -> permissions `Mail.ReadWrite`, `MailboxSettings.ReadWrite`, `offline_access` -> client secret.

| # | Step | Expected |
|---|---|---|
| 5.1 | "Conectar Gmail" / "Conectar Outlook", grant access | Returns JSON with `account_id` (no redirect to the UI yet, see BACKLOG); the account is listed after reload |
| 5.2 | Gmail consent screen | Asks for basic settings (filters) in addition to read/modify |
| 5.3 | Deny consent | Clear 400, nothing breaks |
| 5.4 | Scan the mailbox with the 4 newsletter emails | "Regras sugeridas": "Criar regra: emails de X -> mover para Y", "N de M emails" |
| 5.5 | Approve the rule | Success. **Verify in the webmail:** Gmail Settings -> Filters; Outlook Settings -> Rules |
| 5.6 | Gmail filter behaviour | Labels **and** removes from Inbox; send a new email from that sender to confirm |
| 5.7 | Domain rule | Appears as "do domínio" when no single sender reaches the threshold but the domain does |
| 5.8 | Scan the same mailbox again | The applied rule is **not** proposed again |
| 5.9 | Approve a second proposal for the same sender | Error "Já existe uma regra"; nothing created |
| 5.10 | Check that no rule ever targets Trash/Spam/Inbox | If one appears it is a serious bug: record it |

Specifically record: does the Gmail `from: *@domain` filter actually match? What does the
Outlook "contains" condition match?

## 6. Security smoke tests (terminal)

```powershell
curl.exe -i -X POST http://localhost:8000/proposals/1/approve
# expected: 403 (missing X-Requested-With)
curl.exe -i -H "Host: evil.example" http://localhost:8000/accounts
# expected: 400 (invalid host)
curl.exe -i http://localhost:8000/accounts
# expected: 200, accounts listed WITHOUT passwords or tokens
```

## 7. Robustness

| # | Step | Expected |
|---|---|---|
| 7.1 | Restart the server in the middle of a scan | Job stays `running` (known limitation); a new scan works |
| 7.2 | Start with an `app.db` from an older version | Starts normally, data preserved |
| 7.3 | Revoke the app's access in the Google account, then list folders | Clear 502, no broken page |

## Inspecting state when something looks wrong

```powershell
python -c "import sqlite3;c=sqlite3.connect(r'C:\temp\mo-test\app.db');c.row_factory=sqlite3.Row;[print(dict(r)) for r in c.execute('select id,action,target_folder,applied_status,applied_error,rule_kind,rule_value from proposals order by id desc limit 15')]"
```

## Results

Copy this table per run. Result: `pass`, `fail` (link the issue or add a BACKLOG item) or `skip`.

| Date | Tester | Commit | Provider | Sections run | Result | Notes / BACKLOG items opened |
|---|---|---|---|---|---|---|
| _not run yet_ | | | | | | |
