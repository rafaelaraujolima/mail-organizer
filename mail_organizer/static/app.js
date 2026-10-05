// mail_organizer/static/app.js
// Security: values from email/LLM/provider/server are only ever rendered via
// textContent (ADR-0006). The sole HTML sink is a sandboxed iframe srcdoc.
const ACTION_LABELS = {
  move: "Mover",
  flag_delete: "Possível lixo/phishing",
  keep: "Manter",
  error: "Erro",
};

function byId(id) {
  return document.getElementById(id);
}

function showStatus(message) {
  byId("status").textContent = message || "";
}

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function makeEl(tag, { className, text } = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function errorMessage(err) {
  return err && err.message ? err.message : String(err);
}

// Every non-GET request carries the custom header the API requires (CSRF defence, ADR-0013).
async function fetchJSON(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET") {
    options = { ...options, headers: { ...options.headers, "X-Requested-With": "mail-organizer" } };
  }
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    let detail = body.detail;
    if (detail !== undefined && typeof detail !== "string") detail = JSON.stringify(detail);
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

function postJSON(url, payload) {
  const options = { method: "POST" };
  if (payload !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(payload);
  }
  return fetchJSON(url, options);
}

async function loadAccounts() {
  const accounts = await fetchJSON("/accounts");
  const list = byId("account-list");
  const select = byId("account-select");
  clearChildren(list);
  clearChildren(select);

  for (const account of accounts) {
    list.appendChild(makeEl("li", { text: `${account.display_name} (${account.provider})` }));

    const option = makeEl("option", { text: account.display_name });
    option.value = account.account_id;
    select.appendChild(option);
  }

  byId("scan-section").hidden = accounts.length === 0;
  if (accounts.length > 0) {
    await loadFolders(select.value);
  }
}

async function loadFolders(accountId) {
  if (!accountId) return;
  const folders = await fetchJSON(`/accounts/${encodeURIComponent(accountId)}/folders`);
  const select = byId("folder-select");
  clearChildren(select);
  for (const folder of folders) {
    const option = makeEl("option", { text: folder.name });
    option.value = folder.id;
    select.appendChild(option);
  }
}

async function refreshAccounts() {
  try {
    await loadAccounts();
    showStatus("");
  } catch (err) {
    showStatus(errorMessage(err));
  }
}

byId("account-select").addEventListener("change", async (event) => {
  try {
    await loadFolders(event.target.value);
    showStatus("");
  } catch (err) {
    showStatus(errorMessage(err));
  }
});

byId("imap-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formEl = event.target;
  const form = new FormData(formEl);
  const errorEl = byId("imap-error");
  errorEl.textContent = "";

  try {
    await postJSON("/accounts/imap", {
      display_name: form.get("display_name"),
      host: form.get("host"),
      port: Number(form.get("port")),
      username: form.get("username"),
      password: form.get("password"),
    });
    formEl.reset();
    await loadAccounts();
  } catch (err) {
    errorEl.textContent = errorMessage(err);
  }
});

let currentJobId = null;
let pollTimer = null;

byId("start-scan").addEventListener("click", async () => {
  const accountId = byId("account-select").value;
  const folder = byId("folder-select").value;
  const days = byId("days-filter").value;
  const filters = days ? { days: Number(days) } : {};

  clearTimeout(pollTimer);
  try {
    const { job_id } = await postJSON("/scan", { account_id: accountId, folder, filters });
    currentJobId = job_id;
    showStatus("");
    byId("proposals-section").hidden = false;
    clearChildren(byId("proposal-list"));
    await pollJob();
  } catch (err) {
    showStatus(errorMessage(err));
  }
});

async function pollJob() {
  if (!currentJobId) return;
  try {
    const job = await fetchJSON(`/jobs/${encodeURIComponent(currentJobId)}`);
    byId("job-status").textContent =
      `Status: ${job.status} (${job.processed}/${job.total})` +
      (job.error_message ? ` — ${job.error_message}` : "");

    if (job.status === "running") {
      pollTimer = setTimeout(pollJob, 1500);
    } else {
      clearTimeout(pollTimer);
      await loadProposals();
    }
  } catch (err) {
    clearTimeout(pollTimer);
    showStatus(errorMessage(err));
  }
}

async function toggleContent(proposal, holder, errorEl, viewButton) {
  errorEl.textContent = "";
  if (holder.firstChild) {
    clearChildren(holder);
    return;
  }
  viewButton.disabled = true;
  try {
    const data = await fetchJSON(
      `/jobs/${encodeURIComponent(currentJobId)}/messages/${encodeURIComponent(proposal.message_id)}/content`
    );
    // Re-check after the await so two iframes can never be appended.
    if (holder.firstChild) return;
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "");
    iframe.srcdoc = data.html;
    holder.appendChild(iframe);
  } catch (err) {
    errorEl.textContent = errorMessage(err);
  } finally {
    viewButton.disabled = false;
  }
}

function buildProposal(proposal) {
  const pending = proposal.applied_status === "pending";
  const div = makeEl("div", {
    className: "proposal" + (proposal.action === "flag_delete" ? " suspicious" : ""),
  });

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "proposal-checkbox";
  checkbox.value = String(proposal.id);
  checkbox.disabled = !pending;
  div.appendChild(checkbox);

  div.appendChild(makeEl("strong", { text: ACTION_LABELS[proposal.action] || String(proposal.action) }));
  if (proposal.target_folder) {
    div.appendChild(makeEl("span", { text: ` → ${proposal.target_folder}` }));
  }
  div.appendChild(makeEl("div", { className: "reason", text: proposal.reason || "" }));
  div.appendChild(
    makeEl("div", {
      text: `Status: ${proposal.applied_status}` + (proposal.applied_error ? ` — ${proposal.applied_error}` : ""),
    })
  );

  const errorEl = makeEl("div", { className: "error proposal-error" });
  const holder = makeEl("div", { className: "content-holder" });

  const approve = makeEl("button", { className: "approve-one", text: "Aprovar" });
  approve.disabled = !pending;
  approve.addEventListener("click", async () => {
    // Lock synchronously, before the await; only the list reload re-enables.
    lockActions();
    errorEl.textContent = "";
    let failure = null;
    try {
      await postJSON(`/proposals/${proposal.id}/approve`);
    } catch (err) {
      failure = { id: proposal.id, message: errorMessage(err) };
    }
    // Reload to reflect the new applied_status; re-show the failure afterwards.
    await loadProposals(failure);
  });

  const reject = makeEl("button", { className: "reject-one", text: "Rejeitar" });
  reject.disabled = !pending;
  reject.addEventListener("click", async () => {
    lockActions();
    errorEl.textContent = "";
    let failure = null;
    try {
      await postJSON(`/proposals/${proposal.id}/reject`);
    } catch (err) {
      failure = { id: proposal.id, message: errorMessage(err) };
    }
    await loadProposals(failure);
  });

  const view = makeEl("button", { className: "view-content", text: "Ver conteúdo" });
  view.addEventListener("click", () => toggleContent(proposal, holder, errorEl, view));

  function lockActions() {
    approve.disabled = true;
    reject.disabled = true;
    checkbox.disabled = true;
  }

  div.append(approve, reject, view, errorEl, holder);
  return div;
}

// keepError: optional {id, message} so a failed action stays visible after reload.
async function loadProposals(keepError) {
  try {
    const proposals = await fetchJSON(`/jobs/${encodeURIComponent(currentJobId)}/proposals`);
    const container = byId("proposal-list");
    clearChildren(container);
    for (const proposal of proposals) {
      const node = buildProposal(proposal);
      if (keepError && keepError.id === proposal.id) {
        node.querySelector(".proposal-error").textContent = keepError.message;
      }
      container.appendChild(node);
    }
  } catch (err) {
    showStatus(errorMessage(err));
  }
}

byId("approve-selected").addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".proposal-checkbox:checked")).map((el) => Number(el.value));
  if (ids.length === 0) return;
  const summary = byId("batch-summary");
  const errorList = byId("batch-errors");
  clearChildren(errorList);
  summary.textContent = "";

  try {
    const result = await postJSON("/proposals/batch-approve", { ids });
    let ok = 0;
    let failed = 0;
    for (const [id, outcome] of Object.entries(result)) {
      if (outcome === "ok") {
        ok += 1;
      } else {
        failed += 1;
        errorList.appendChild(makeEl("li", { text: `Proposta ${id}: ${outcome}` }));
      }
    }
    summary.textContent = `${ok} aplicadas, ${failed} com erro`;
    await loadProposals();
  } catch (err) {
    showStatus(errorMessage(err));
  }
});

refreshAccounts();
