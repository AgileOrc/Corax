// Document Hub: the web frontend of the document app (demo/app), protected by Corax.
// Plain JavaScript, no build step. Every API call goes through the gateway (Envoy -> OPA -> the AI
// risk check) like any other client's; only these files and POST /auth/login skip the check.
// Routes: #/login, #/documents, #/documents/<id>, #/shared, #/requests, #/admin[/<tab>],
// #/admin/request/<id>, #/rules.
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const app = () => $("#app");

// --- helpers --------------------------------------------------------------------------------------

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const short = (id) => String(id ?? "").replace(/^[a-z]+_/, "");                  // employee_E037 -> E037
const words = (s) => String(s ?? "").replace(/_/g, " ");
const titled = (s) => words(s).replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bHr\b/g, "HR");  // security_officer -> Security Officer
const project = (p) => titled(String(p ?? "").replace(/(\D)(\d+)$/, "$1 $2"));     // engineering1 -> Engineering 1
const article = (w) => `${/^[aeiou]/i.test(w) ? "an" : "a"} ${w}`;
const initials = (name) => String(name ?? "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const LEVEL = { public: "ok", internal: "info", confidential: "no" };
let departments = null;  // the catalog's departments, read once after signing in (they depend on the data)
const LEVELS = ["public", "internal", "confidential"];

function ago(iso) {
  if (!iso) return "";
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

// The request statuses of the document app, for employees and for admins.
// What the employee sees: only whether they can read the document, never the rule, its scope or how
// Corax decided (that is for admins).
const EMPLOYEE_STATUS = {
  pending: ["Pending", "Waiting for an admin."],
  granted: ["Approved", "You can read this document."],
  generalised: ["Approved", "You can read this document."],
  exception_only: ["Approved", "You can read this document."],
  rule_revoked: ["Approved", "You can read this document."],
  already_granted: ["Approved", "You could read this document already."],
  rejected: ["Rejected", "An admin rejected the request."],
  revoked: ["Revoked", "An admin took the access back."],
};
const employeeBadge = (status) => {
  const [label] = EMPLOYEE_STATUS[status] || [status];
  const kind = { Pending: "warn", Approved: "ok" }[label] || "no";
  return `<span class="badge ${kind}"><span class="dot"></span>${esc(label)}</span>`;
};

// What the admin sees.
const STATUS = {
  pending: ["warn", "Pending", "Waiting for an admin."],
  granted: ["ok", "Approved", "Approved for this document. You can still give the same access to people in the same situation."],
  generalised: ["ok", "Approved · also for others", "Approved, and people in the same situation got the same access."],
  exception_only: ["ok", "Approved · this person only", "Approved for this document and this person only."],
  rejected: ["no", "Rejected", "An admin rejected the request."],
  already_granted: ["info", "Already allowed", "The employee could read the document already."],
  rule_revoked: ["warn", "Taken back from others", "The access for people in the same situation was taken back. This person keeps this one document."],
  revoked: ["no", "Revoked", "An admin took the access back."],
};
const statusBadge = (status) => {
  const [kind, label] = STATUS[status] || ["", status];
  return `<span class="badge ${kind}"><span class="dot"></span>${esc(label)}</span>`;
};
// a site and its region: "Paris (EMEA)"
const place = (site, region) => site ? `${titled(site)} (${String(region || "").toUpperCase()})` : "";
const levelBadge = (level) => `<span class="badge ${LEVEL[level] || ""}">${esc(titled(level))}</span>`;

// A candidate pattern in words, from its predicates (service/patterns.py).
const SHARED = {
  "works_in/owned_by": "the document belongs to their department",
  "based_in/stored_in": "the document is stored in their region",
  "located_in/stored_at": "the document is stored at their site",
  "works_on/belongs_to": "the document is in one of their projects",
  "cleared_for/classified_as": "they are cleared for the document's classification",
  "supports/owned_by": "the document belongs to the department they support",
};
const USER_HAS = {
  holds: (v) => `they are ${article(words(v))}`,
  works_in: (v) => `they work in ${titled(v)}`,
  member_of: (v) => `they are in team ${project(v)}`,
  located_in: (v) => `they work at the ${titled(v)} site`,
  based_in: (v) => `they are based in ${v.toUpperCase()}`,
  works_on: (v) => `they work on ${project(v)}`,
  reports_to: (v) => `they report to ${v}`,
  supports: (v) => `they support ${titled(v)}`,
  cleared_for: (v) => `they are cleared for ${v} documents`,
};
// The sentence of a rule the app stored by its technical pattern: Corax's description of that
// candidate, else the app's own wording of its predicates.
function ruleText(r, pattern) {
  const c = (r.candidates || []).find((x) => x.pattern === pattern);
  return c ? c.description || inWords(c.predicates) : "A rule for people in the same situation.";
}

function inWords(predicates) {
  const parts = (predicates || []).map((p) => {
    const other = short(p.other);
    if (p.kind === "shared") return SHARED[`${p.relation}/${p.other}`] || `their ${words(p.relation)} is the document's ${words(p.other)}`;
    if (p.kind === "user_has") return (USER_HAS[p.relation] || ((v) => `they ${words(p.relation)} ${v}`))(other);
    if (p.kind === "object_has") return `the document ${words(p.relation)} ${words(other)}`;
    return `the document is ${other}`;
  });
  return parts.length ? `Applies when ${parts.join(", and ")}.` : "";
}

// --- session and API ------------------------------------------------------------------------------

const session = {
  get token() { return sessionStorage.getItem("token"); },
  get user() { try { return JSON.parse(sessionStorage.getItem("user")); } catch { return null; } },
  save(token, user) { sessionStorage.setItem("token", token); sessionStorage.setItem("user", JSON.stringify(user)); },
  clear() { sessionStorage.removeItem("token"); sessionStorage.removeItem("user"); },
  valid() {
    const token = this.token;
    if (!token || !this.user) return false;
    try {
      const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return payload.exp * 1000 > Date.now() + 5000;
    } catch { return false; }
  },
};

// fetch through the gateway. Returns {status, data}; status 0 when the session ended or the gateway
// is unreachable (then the page has already moved on). A request Corax denies comes back as 403.
async function api(method, path, body) {
  const login = path === "/auth/login";
  if (!login && !session.valid()) { signOut("Your session has ended. Please sign in again."); return { status: 0, data: null }; }
  const headers = {};
  if (!login) headers.Authorization = `Bearer ${session.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    toast("The gateway is not reachable.", "no");
    return { status: 0, data: null };
  }
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { text }; }
  return { status: response.status, data };
}

const errorText = (answer) => {
  const d = answer.data || {};
  const detail = typeof d.detail === "string" ? d.detail : d.detail?.message || d.error || d.text;
  return detail ? `${answer.status}: ${detail}` : `The request failed (${answer.status}).`;
};

// --- rendering ------------------------------------------------------------------------------------

let ticket = 0;      // the route being shown; a slower, older view must not overwrite a newer one
let flash = null;    // a message for the next view

function render(mine, html) {
  if (mine !== ticket) return false;
  app().innerHTML = (flash ? flash : "") + html;
  flash = null;
  return true;
}

function toast(text, kind = "") {
  const element = document.createElement("div");
  element.className = `toast ${kind}`;
  element.textContent = text;
  $("#toasts").append(element);
  setTimeout(() => element.remove(), 4500);
}

function showModal(html) {
  closeModal();
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.id = "modal";
  backdrop.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  document.body.append(backdrop);
  ($("input, textarea, button", backdrop) || backdrop).focus();
}
const closeModal = () => $("#modal")?.remove();
const modalHead = (title) => `<div class="modal-head"><h2>${esc(title)}</h2>
  <button class="button ghost small" type="button" data-action="close-modal" aria-label="Close">Close</button></div>`;

function renderShell() {
  const user = session.user;
  const signedIn = session.valid();
  $("#topbar").hidden = !signedIn;
  $("#footer").hidden = !signedIn;
  if (!signedIn) return;
  const admin = user.kind === "admin";
  const links = admin
    ? [["#/admin", "Access requests"], ["#/unit-requests", "Unit requests"], ["#/suggestions", "Suggested access"],
       ["#/grant", "Give access"], ["#/rules", "Access granted"], ["#/documents", "Documents"]]
    : [["#/documents", "Documents"], ["#/shared", "Shared with me"], ["#/units", "Ask for a unit"], ["#/requests", "My requests"]];
  $("#nav").innerHTML = links.map(([href, label]) => `<a href="${href}" data-nav="${href}">${esc(label)}</a>`).join("");
  $("#whoName").innerHTML = admin
    ? `<b>${esc(user.name)}</b> · reviews access requests`
    : `<b>${esc(user.name)}</b> · ${esc(titled(user.role))}, ${esc(titled(user.department))} · ${esc(place(user.site, user.region))}`;
  const hash = location.hash;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", hash.startsWith(a.dataset.nav)));
}

function signOut(message) {
  session.clear();
  Object.assign(filters, { q: "", department: "", classification: "", mine: false });  // not the next user's
  departments = null;
  directory = null;
  closeModal();
  if (message) toast(message);
  location.hash = "#/login";
}

// --- sign in --------------------------------------------------------------------------------------

// The demo accounts: those of the prepared data (assets/accounts.json, written by scripts/demo_office.py
// prepare), or these, of the enterprise of scripts/prepare/make_enterprise.py.
const ACCOUNTS = [
  ["e049", "Engineering coordinator"], ["e085", "Finance coordinator"], ["e040", "Engineer"],
  ["e003", "Sales analyst"], ["e001", "Sales manager"], ["e076", "Auditor"], ["admin_01", "Corax admin"],
];

async function demoAccounts() {
  try {
    const response = await fetch("/assets/accounts.json");
    const accounts = response.ok ? (await response.json()).accounts : null;
    if (Array.isArray(accounts) && accounts.length) return accounts.map((a) => [a.username, a.label]);
  } catch { /* no prepared accounts: the built-in ones */ }
  return ACCOUNTS;
}

const accountButtons = (accounts) => accounts.map(([user, label]) => `
  <button class="account" type="button" data-action="fill-account" data-user="${esc(user)}"><b>${esc(user)}</b><span>${esc(label)}</span></button>`).join("");

function viewLogin(mine) {
  if (!render(mine, `
  <div class="login">
    <section class="card">
      <div class="brand"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2h8l4 4v16H6z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 2v4h4M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>Document Hub</span></div>
      <h1>Sign in</h1>
      <p class="muted">The demo document app. Corax decides who may read what.</p>
      <form data-form="login" novalidate>
        <div class="field"><label for="username">Username</label>
          <input id="username" name="username" autocomplete="username" placeholder="e.g. e029 or employee_E029" required></div>
        <div class="field"><label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password" required></div>
        <p class="small error" id="loginError" role="alert"></p>
        <button class="button" type="submit">Sign in</button>
      </form>
      <div class="stack">
        <p class="small muted">Demo accounts, all with the password <code>corax-demo</code>:</p>
        <div class="accounts" id="accounts"></div>
      </div>
    </section>
  </div>`)) return;
  $("#username")?.focus();
  demoAccounts().then((accounts) => { if (mine === ticket && $("#accounts")) $("#accounts").innerHTML = accountButtons(accounts); });
}

async function signIn(form) {
  const username = form.username.value.trim();
  const password = form.password.value;
  const error = $("#loginError");
  if (!username || !password) { error.textContent = "Enter a username and a password."; return; }
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const answer = await api("POST", "/auth/login", { username, password });
  button.disabled = false;
  if (answer.status === 200) {
    session.save(answer.data.token, answer.data.user);
    location.hash = answer.data.user.kind === "admin" ? "#/admin" : "#/documents";
  } else {
    error.textContent = answer.status === 401 ? "Wrong username or password." : errorText(answer);
  }
}

// --- documents ------------------------------------------------------------------------------------

const filters = { q: "", department: "", classification: "", mine: false };

async function viewDocuments(mine) {
  if (!departments) {
    const all = await api("GET", "/documents");
    if (all.status === 0) return;
    if (all.status === 200) departments = [...new Set(all.data.documents.map((d) => d.department))].sort();
  }
  const admin = session.user.kind === "admin";
  const shared = admin ? null : await sharedWithMe();
  const banner = shared?.fresh.length ? `<div class="notice ok"><h3>${shared.fresh.length} new document${shared.fresh.length === 1 ? " was" : "s were"} shared with you</h3>
      <p>An admin approved access for people in your situation. <a href="#/shared">See them under Shared with me</a>.</p></div><br>` : "";
  const option = (value, current) => `<option value="${value}"${value === current ? " selected" : ""}>${esc(titled(value))}</option>`;
  if (!render(mine, `${banner}
    <div class="page-head">
      <div><h1>Documents</h1><p>${admin ? "Every document, to give access. Reading documents is for employees." : "The documents you can open. Need something else? Ask for it from its link, or <a href=\"#/units\">ask for a unit</a>."}</p></div>
    </div>
    <section class="card">
      <form class="toolbar" data-form="filters" role="search">
        <div class="search"><label for="q">Search</label><input id="q" data-filter="q" placeholder="Title or id, e.g. D057" value="${esc(filters.q)}"></div>
        <div><label for="department">Department</label><select id="department" data-filter="department"><option value="">All</option>${(departments || []).map((d) => option(d, filters.department)).join("")}</select></div>
        <div><label for="classification">Classification</label><select id="classification" data-filter="classification"><option value="">All</option>${LEVELS.map((l) => option(l, filters.classification)).join("")}</select></div>
        ${admin ? "<div></div>" : `<label class="check"><input type="checkbox" data-filter="mine"${filters.mine ? " checked" : ""}> My projects</label>`}
      </form>
      <p class="small muted" id="docCount"></p>
      <ul class="doc-list" id="docList"><li class="empty">Loading…</li></ul>
    </section>`)) return;
  loadDocuments(mine);
}

let filterTimer = null;
async function loadDocuments(mine) {
  const query = new URLSearchParams();
  for (const key of ["q", "department", "classification"]) if (filters[key]) query.set(key, filters[key]);
  const answer = await api("GET", `/documents?${query}`);
  if (mine !== ticket || !$("#docList")) return;
  if (answer.status !== 200) { $("#docList").innerHTML = `<li class="empty">${esc(errorText(answer))}</li>`; return; }
  const admin = session.user.kind === "admin";
  const documents = answer.data.documents.filter((d) => !filters.mine || d.in_my_projects);
  $("#docCount").textContent = `${documents.length} document${documents.length === 1 ? "" : "s"}`;
  $("#docList").innerHTML = documents.length ? documents.map((d) => `
    <li class="doc">
      <div>
        <a class="doc-title" href="#/documents/${esc(d.id)}">${esc(d.title)}</a>
        <div class="doc-meta">
          <span class="mono">${esc(short(d.id))}</span>${levelBadge(d.classification)}
          <span>${esc(titled(d.department))} · ${d.projects.map((p) => esc(project(p))).join(", ")}</span>
          <span>Stored at ${esc(place(d.site, d.region))}</span>
          ${d.in_my_projects ? '<span class="badge accent">Your project</span>' : ""}
        </div>
      </div>
      ${admin ? "" : `<div class="doc-actions">
        <button class="button ghost small" type="button" data-action="preview" data-id="${esc(d.id)}">Preview</button>
        <a class="button small" href="#/documents/${esc(d.id)}">Open</a></div>`}
    </li>`).join("") : '<li class="empty">No documents match.</li>';
}

async function preview(id) {
  showModal(`${modalHead("Preview")}<p class="muted">Asking Corax…</p>`);
  const answer = await api("GET", `/documents/${encodeURIComponent(id)}/summary`);
  if (!$("#modal")) return;
  let body;
  if (answer.status === 200) {
    const d = answer.data;
    body = `<h3>${esc(d.title)}</h3>
      <div class="doc-meta">${levelBadge(d.classification)}<span>${esc(titled(d.department))}</span><span>Stored at ${esc(place(d.site, d.region))}</span></div>
      <div class="content">${esc(d.summary)}</div>`;
  } else if (answer.status === 403) {
    body = `<div class="notice no"><h3>Corax blocked this preview</h3>
      <p>You cannot preview this document.</p></div>`;
  } else {
    body = `<div class="notice warn"><p>${esc(errorText(answer))}</p></div>`;
  }
  $(".modal", $("#modal")).innerHTML = modalHead("Preview") + body;
}

async function viewDocument(mine, id) {
  const answer = await api("GET", `/documents/${encodeURIComponent(id)}`);
  if (answer.status === 0) return;
  const back = '<a href="#/documents" class="small">← Documents</a>';
  if (answer.status === 200) {
    const d = answer.data;
    render(mine, `${back}
      <div class="page-head"><div><h1>${esc(d.title)}</h1><p class="mono">${esc(d.id)}</p></div>
        <span class="badge ok"><span class="dot"></span>Corax allowed it</span></div>
      <div class="grid-2">
        <section class="card"><h2>Content</h2><div class="content">${esc(d.content)}</div></section>
        <section class="card">${metaTable(d)}</section>
      </div>`);
    return;
  }
  // A document that does not exist and one the user may not open look the same: the page shows no
  // title or details, so nobody learns from it which documents exist.
  if (![403, 404].includes(answer.status)) { render(mine, `${back}<div class="card"><div class="notice warn">${esc(errorText(answer))}</div></div>`); return; }

  const mineAnswer = session.user.kind === "employee" ? await api("GET", "/access-requests") : null;
  const requests = mineAnswer?.status === 200 ? mineAnswer.data.requests.filter((r) => r.document_id === id) : [];
  const pending = requests.find((r) => r.status === "pending");
  const ask = session.user.kind !== "employee"
    ? '<p class="muted">Admins do not read documents here; they review the employees\' requests.</p>'
    : pending
      ? `<div class="notice info"><h3>Your request is pending</h3><p>Request #${pending.id}, sent ${esc(ago(pending.created_at))}. You can follow it under <a href="#/requests">My requests</a>.</p></div>`
      : `<form data-form="request-access" data-id="${esc(id)}" class="stack">
          <div><label for="reason">Why do you need it?</label>
            <textarea id="reason" name="reason" maxlength="1000" placeholder="e.g. I coordinate all engineering projects"></textarea></div>
          <button class="button" type="submit">Request access</button>
        </form>`;
  render(mine, `${back}
    <div class="page-head"><div><h1>No access</h1></div>
      <span class="badge no"><span class="dot"></span>Denied by Corax</span></div>
    <section class="card stack">
      <div class="notice no"><h3>You do not have access to this document</h3>
        <p>If someone shared this link with you, you can ask an admin for access. Need documents of a whole unit instead? <a href="#/units">Ask for a unit</a>.</p></div>
      ${ask}
    </section>`);
}

const metaTable = (d) => `<table class="meta-table">
  <tr><td>Classification</td><td>${levelBadge(d.classification)}</td></tr>
  <tr><td>Department</td><td>${esc(titled(d.department))}</td></tr>
  <tr><td>Projects</td><td>${(d.projects || []).map((p) => esc(project(p))).join(", ")}</td></tr>
  <tr><td>Stored at</td><td>${esc(place(d.site, d.region))}</td></tr>
</table>`;

async function requestAccess(form) {
  const id = form.dataset.id;
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const answer = await api("POST", `/access-requests/${encodeURIComponent(id)}`, { reason: form.reason.value.trim() || null });
  if (answer.status === 201) {
    const r = answer.data;
    // granted at once: show the document itself. The employee only needs to know it opens, not the
    // rule behind it (that is for admins, under Access granted).
    const granted = '<div class="notice ok"><h3>Access granted</h3><p>You can read this document now.</p></div><br>';
    const opened = {
      generalised: granted,
      granted,
      already_granted: '<div class="notice info"><h3>You can read it already</h3></div><br>',
    }[r.status];
    if (opened) {
      flash = opened;
      route();
    } else {
      form.outerHTML = `<div class="notice ok"><h3>Request sent</h3><p>Your request is waiting for an admin. Follow it under <a href="#/requests">My requests</a>.</p></div>`;
    }
  } else {
    button.disabled = false;
    toast(answer.status === 409 ? "You already have a pending request for this document." : errorText(answer), "no");
  }
}

// --- shared with me -------------------------------------------------------------------------------

// The documents this employee can read because an admin approved an access request: their own, and
// those of a rule for people in the same situation, which they never asked for. Corax answers it from
// the token alone (GET /corax/me/access). Which ones are new is remembered in this browser only.
const seenKey = () => `corax.shared.${session.user?.id}`;
function seenShared() {
  try { return new Set(JSON.parse(localStorage.getItem(seenKey()) || "[]")); } catch { return new Set(); }
}
function markShared(ids) {
  try { localStorage.setItem(seenKey(), JSON.stringify(ids)); } catch { /* no storage: everything stays new */ }
}

async function sharedWithMe() {
  const answer = await api("GET", "/corax/me/access");
  if (answer.status !== 200) return null;
  const ids = answer.data.resources || [];
  const seen = seenShared();
  return { ids, fresh: ids.filter((id) => !seen.has(id)) };
}

async function viewShared(mine) {
  const [shared, catalog] = await Promise.all([sharedWithMe(), api("GET", "/documents")]);
  if (catalog.status === 0) return;
  if (!shared) { render(mine, '<div class="card notice warn">Corax did not answer. Try again later.</div>'); return; }
  const byId = new Map((catalog.data?.documents || []).map((d) => [d.id, d]));
  const fresh = new Set(shared.fresh);
  const rows = shared.ids.map((id) => {
    const d = byId.get(id) || { id, title: id, projects: [] };
    return `<li class="doc">
      <div>
        <a class="doc-title" href="#/documents/${esc(id)}">${esc(d.title)}</a>
        <div class="doc-meta"><span class="mono">${esc(short(id))}</span>${d.classification ? levelBadge(d.classification) : ""}
          ${d.department ? `<span>${esc(titled(d.department))}</span>` : ""}
          ${fresh.has(id) ? '<span class="badge accent">New</span>' : ""}</div>
      </div>
      <div class="doc-actions"><a class="button small" href="#/documents/${esc(id)}">Open</a></div>
    </li>`;
  });
  if (!render(mine, `
    <div class="page-head"><div><h1>Shared with me</h1>
      <p>Documents you can read because an admin approved access: your own requests, and rules for people in your situation that you never had to ask for.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <section class="card"><ul class="doc-list">${rows.length ? rows.join("") : '<li class="empty">Nothing shared with you yet.</li>'}</ul>
      <p class="small muted">Documents your own projects and role already give you are not listed here.</p></section>`)) return;
  markShared(shared.ids);
}

// --- my requests ----------------------------------------------------------------------------------

async function viewMyRequests(mine) {
  const answer = await api("GET", "/access-requests");
  if (answer.status === 0) return;
  if (answer.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(answer))}</div>`); return; }
  const requests = answer.data.requests;
  render(mine, `
    <div class="page-head"><div><h1>My requests</h1><p>Documents you asked for, and what the admin decided.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <section class="card">${requests.length ? requests.map((r) => `
      <article class="request">
        <div>
          <h3><a href="#/documents/${esc(r.document_id)}">${esc(r.document_title || `Document ${short(r.document_id)}`)}</a> ${employeeBadge(r.status)}</h3>
          <p class="small muted">#${r.id} · ${esc(short(r.document_id))}${r.document_classification ? ` · ${levelBadge(r.document_classification)}` : ""} · sent ${esc(ago(r.created_at))}${r.decided_at ? ` · decided ${esc(ago(r.decided_at))}` : ""}</p>
          ${r.reason ? `<p class="reason">“${esc(r.reason)}”</p>` : ""}
          <p class="status-line">${esc((EMPLOYEE_STATUS[r.status] || [])[1] || "")}</p>
          ${r.note ? `<p class="small muted">Note: ${esc(r.note)}</p>` : ""}
        </div>
        <div class="actions">${["granted", "generalised", "exception_only", "already_granted"].includes(r.status)
          ? `<a class="button small" href="#/documents/${esc(r.document_id)}">Open document</a>` : ""}</div>
      </article>`).join("") : '<p class="empty">No requests yet. When Corax denies a document, ask for access from its page.</p>'}
    </section>`);
}

const tierBadge = (tier) => tier ? `<span class="badge ${tier === "small" ? "ok" : "warn"}">${tier === "small" ? "few people" : "many people"}</span>` : "";

// --- admin: access requests -----------------------------------------------------------------------

const TABS = [
  ["pending", "Pending", (r) => r.status === "pending"],
  ["granted", "Your decision", (r) => r.status === "granted"],
  ["decided", "Decided", (r) => !["pending", "granted"].includes(r.status)],
  ["all", "All", () => true],
];

async function viewAdmin(mine, tab = "pending") {
  const answer = await api("GET", "/admin/access-requests");
  if (answer.status === 0) return;
  if (answer.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(answer))}</div>`); return; }
  const all = answer.data.requests;
  const [, , keep] = TABS.find(([key]) => key === tab) || TABS[0];
  const shown = all.filter(keep);
  render(mine, `
    <div class="page-head"><div><h1>Access requests</h1>
      <p>Every request waits for you. Approve to give the employee the document, then decide whether people in the same situation get it too.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <nav class="tabs">${TABS.map(([key, label, test]) => `
      <a href="#/admin/${key}" class="${key === tab ? "active" : ""}">${esc(label)} <span class="badge">${all.filter(test).length}</span></a>`).join("")}</nav>
    <section class="card">${shown.length ? shown.map(requestRow).join("") : '<p class="empty">Nothing here.</p>'}</section>`);
}

const person = (r) => `<div class="person"><span class="avatar">${esc(initials(r.user_name))}</span>
  <div><b>${esc(r.user_name)}</b> <span class="muted small">${esc(short(r.user_id))}</span>
  <div class="small muted">${esc(titled(r.user_role))}, ${esc(titled(r.user_department))} · ${esc(place(r.user_site, r.user_region))}</div></div></div>`;

const requestRow = (r) => `
  <article class="request">
    <div class="stack">
      ${person(r)}
      <div><span class="muted small">${r.requested_by && r.requested_by !== r.user_id ? `given by ${esc(r.requested_by)}:` : "asks for"}</span> <b>${esc(r.document_title)}</b> <span class="muted small">${esc(short(r.document_id))}</span>
        ${levelBadge(r.document_classification)} <span class="small muted">${esc(titled(r.document_department))} · stored at ${esc(place(r.document_site, r.document_region))}</span></div>
      ${r.reason ? `<p class="reason">“${esc(r.reason)}”</p>` : ""}
      <p class="small muted">#${r.id} · ${esc(ago(r.created_at))} ${statusBadge(r.status)}${r.rule_pattern ? ` · ${esc(ruleText(r, r.rule_pattern))} ${tierBadge(r.tier)}` : ""}</p>
    </div>
    <div class="actions">${r.status === "pending" ? `
      <button class="button ok small" type="button" data-action="approve" data-id="${r.id}">Approve</button>
      <button class="button ghost small" type="button" data-action="reject" data-id="${r.id}">Reject</button>` : ""}
      ${r.status === "granted" ? `<a class="button small" href="#/admin/request/${r.id}">Decide</a>` : ""}
      <a class="button ghost small" href="#/admin/request/${r.id}">Details</a>
    </div>
  </article>`;

async function approve(id, button) {
  button.disabled = true;
  const answer = await api("POST", `/admin/access-requests/${id}/approve`);
  if (answer.status !== 200) {
    button.disabled = false;
    toast(errorText(answer), "no");
    return;
  }
  const { request } = answer.data;
  if (request.status === "granted") {
    flash = `<div class="notice ok"><h3>Approved</h3>
      <p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></div><br>`;
    location.hash = `#/admin/request/${id}`;
  } else {
    toast("The employee could read the document already.");
    route();
  }
}

// The notice after the admin gave a suggestion to people in the same situation.
function ruleNotice(appeal) {
  const scope = appeal.chosen.scope;
  const how = scope.tier === "small"
      ? "Done right away, because it reaches only a few people."
      : "Done after you confirmed it.";
  return `<div class="notice ok"><h3>Access given to people in the same situation ${tierBadge(scope.tier)}</h3>
    <p>${how} It works right away.</p>
    <p>${esc(appeal.chosen.description || "")}</p>${scopeIndicators(scope)}
    <p><a href="#/rules">See who gained access and how it is used</a></p>
    <p class="small muted">Checked automatically before it took effect.</p></div><br>`;
}

function askReject(id) {
  showModal(`${modalHead(`Reject request #${id}`)}
    <form data-form="reject" data-id="${id}" class="stack">
      <div><label for="note">Note for the employee (optional)</label><textarea id="note" name="note" maxlength="1000"></textarea></div>
      <div class="row"><span class="spacer"></span>
        <button class="button ghost" type="button" data-action="close-modal">Cancel</button>
        <button class="button danger" type="submit">Reject</button></div>
    </form>`);
}

async function reject(form) {
  const answer = await api("POST", `/admin/access-requests/${form.dataset.id}/reject`, { note: form.note.value.trim() || null });
  closeModal();
  if (answer.status === 200) { toast(`Request #${form.dataset.id} rejected.`); route(); } else toast(errorText(answer), "no");
}

async function viewAdminRequest(mine, id) {
  const answer = await api("GET", "/admin/access-requests");
  if (answer.status === 0) return;
  const r = answer.status === 200 ? answer.data.requests.find((x) => x.id === Number(id)) : null;
  const back = '<a href="#/admin" class="small">← Access requests</a>';
  if (!r) { render(mine, `${back}<div class="card empty">${answer.status === 200 ? "No such request." : esc(errorText(answer))}</div>`); return; }

  let decision = "";
  if (r.status === "pending") {
    decision = `<div class="row"><button class="button ok" type="button" data-action="approve" data-id="${r.id}">Approve</button>
      <button class="button ghost" type="button" data-action="reject" data-id="${r.id}">Reject</button></div>`;
  } else if (r.status === "granted") {
    const why = r.note ? `<div class="notice info"><p>${esc(r.note)}.</p></div>` : "";
    decision = `${why}<p class="muted">The employee can read the document now. To give the same access to people in the same situation, choose one of Corax's suggestions below, narrowest first.</p>
      ${candidatesTable(r)}
      <div class="row"><span class="spacer"></span><button class="button ghost" type="button" data-action="keep-exception" data-request="${r.id}">Only this person</button></div>
      <div id="result"></div>`;
  } else if (r.status === "generalised") {
    decision = `<div class="notice ok"><h3>Access given to people in the same situation ${tierBadge(r.tier)}</h3><p>${esc(ruleText(r, r.rule_pattern))}</p>
      <p>People in the same situation can read these documents now. Unusual requests from them can still be blocked.</p>
      <div class="row"><a class="button ghost small" href="#/rules">Who gained access</a>
        <button class="button danger small" type="button" data-action="revoke" data-request="${r.id}">Take back from others</button>
        <button class="button ghost small" type="button" data-action="revoke-all" data-request="${r.id}">Take back from everyone</button></div></div>`;
  } else if (["exception_only", "rule_revoked"].includes(r.status) && r.appeal_id) {
    decision = `<div class="notice info"><h3>${esc((STATUS[r.status] || [])[1] || r.status)}</h3><p>${esc((STATUS[r.status] || [])[2] || "")}</p>
      ${r.note ? `<p>Note: ${esc(r.note)}</p>` : ""}
      <div class="row"><button class="button danger small" type="button" data-action="revoke-all" data-request="${r.id}">Revoke the employee's access too</button></div></div>`;
  } else {
    decision = `<div class="notice ${STATUS[r.status]?.[0] === "no" ? "no" : "info"}"><h3>${esc((STATUS[r.status] || [])[1] || r.status)}</h3>
      <p>${esc((STATUS[r.status] || [])[2] || "")}</p>${r.note ? `<p>Note: ${esc(r.note)}</p>` : ""}</div>`;
  }
  render(mine, `${back}
    <div class="page-head"><div><h1>Request #${r.id}</h1><p>${statusBadge(r.status)} sent ${esc(ago(r.created_at))}${r.decided_by ? `, decided by ${esc(r.decided_by)} ${esc(ago(r.decided_at))}` : ""}</p></div></div>
    <div class="grid-2">
      <section class="card stack"><h2>Decision</h2>${decision}</section>
      <section class="card stack">${person(r)}
        <div><span class="muted small">asks for</span><div><b>${esc(r.document_title)}</b> <span class="mono muted">${esc(r.document_id)}</span></div>
          <div class="doc-meta">${levelBadge(r.document_classification)}<span>${esc(titled(r.document_department))}</span><span>Stored at ${esc(place(r.document_site, r.document_region))}</span></div></div>
        ${r.reason ? `<p class="reason">“${esc(r.reason)}”</p>` : '<p class="muted small">No reason given.</p>'}
      </section>
    </div>`);
}

const candidatesTable = (r) => (r.candidates || []).length ? `
  <table class="candidates">
    <thead><tr><th>#</th><th>Suggestion</th><th class="num">People</th><th class="num">New accesses</th><th class="num">How unusual (0–1)</th><th>Reach</th><th class="num">Like this request</th><th></th></tr></thead>
    <tbody>${r.candidates.map((c) => `
      <tr><td>${c.index}</td>
        <td><div>${esc(c.description || inWords(c.predicates))}</div>
          <div><button class="button ghost small" type="button" data-action="who" data-appeal="${esc(r.appeal_id)}" data-candidate="${c.index}">Who would gain access</button></div></td>
        <td class="num">${c.scope?.users ?? c.users ?? "?"}</td><td class="num">${c.scope ? c.scope.pairs : `${c.estimated ? "~" : ""}${c.pairs}`}</td>
        <td class="num">${c.scope?.mean_risk == null ? "–" : Number(c.scope.mean_risk).toFixed(2)}</td><td>${tierBadge(c.scope?.tier)}</td>
        <td class="num">${c.similar ? `${c.similar.covered} of ${c.similar.of}` : `${Math.round((c.support || 0) * 100)}%`}</td>
        <td><button class="button small" type="button" data-action="apply" data-request="${r.id}" data-candidate="${c.index}">Give access</button></td></tr>`).join("")}
    </tbody>
  </table>
  <p class="small muted">Like this request: of the requests most like this one, how many the suggestion would also cover.</p>` : '<p class="muted">Corax has no suggestion for people in the same situation.</p>';

const scopeIndicators = (scope) => `<div class="indicators">
  <div class="indicator"><b>${scope.users}</b><span>people</span></div>
  <div class="indicator"><b>${scope.pairs}</b><span>new accesses (one person, one document)</span></div>
  <div class="indicator"><b>${scope.mean_risk == null ? "–" : Number(scope.mean_risk).toFixed(2)}</b><span>how unusual, on average (0 normal, 1 very unusual)</span></div>
</div>`;

async function confirmPattern(requestId, candidate, acknowledge) {
  document.querySelectorAll("#app button").forEach((b) => { b.disabled = true; });
  const answer = await api("POST", `/admin/access-requests/${requestId}/confirm`, { candidate, acknowledge_scope: acknowledge });
  const result = $("#result");
  const enable = () => document.querySelectorAll("#app button").forEach((b) => { b.disabled = false; });
  if (answer.status === 200) {
    const appeal = answer.data.appeal;
    if (appeal.status === "rule_applied") {
      flash = ruleNotice(appeal);
    } else {
      flash = '<div class="notice ok"><h3>Only the exception was kept</h3><p>The employee has this one document; no rule for others.</p></div><br>';
    }
    route();
    return;
  }
  enable();
  if (answer.status === 409 && answer.data?.appeal?.scope && result) {
    const { scope, description, affected } = answer.data.appeal;
    await loadDirectory();
    result.innerHTML = `<div class="notice warn"><h3>This reaches many people: please confirm</h3>
      <p>Suggestion #${candidate} would give access to many people, or to unusual access, so it needs a second look:</p>
      ${description ? `<p>${esc(description)}</p>` : ""}
      ${scopeIndicators(scope)}
      ${affected ? peopleList(affected) : ""}
      <div class="row"><button class="button" type="button" data-action="ack" data-request="${requestId}" data-candidate="${candidate}">Confirm and give access</button>
        <button class="button ghost" type="button" data-action="keep-exception" data-request="${requestId}">Only this person</button></div></div>`;
    result.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else if (answer.status === 422 && result) {
    result.innerHTML = `<div class="notice no"><h3>Corax could not apply this suggestion</h3><p>A safety check failed, so nothing changed. The employee keeps this one document.</p></div>`;
  } else {
    toast(errorText(answer), "no");
  }
}

// --- admin: give access without being asked -------------------------------------------------------

// The admin gives an employee a document (a new team member, a change of role): it starts approved,
// and Corax proposes the same access for people in the same situation, as for an approved request.
async function viewGrant(mine) {
  const people = await api("GET", "/admin/employees");
  if (people.status === 0) return;
  if (people.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(people))}</div>`); return; }
  const employeeOptions = people.data.employees.map((e) =>
    `<option value="${esc(e.id)}">${esc(e.name)} · ${esc(titled(e.role))}, ${esc(titled(e.department))}</option>`).join("");
  render(mine, `
    <div class="page-head"><div><h1>Give access</h1>
      <p>Give an employee a document without waiting for them to ask, for example someone who joined a team or changed role. Corax then suggests the same access for people in the same situation.</p></div></div>
    <section class="card">
      <form data-form="grant" class="stack">
        <div><label for="grantUser">Employee</label><select id="grantUser" name="user" required><option value="">Choose…</option>${employeeOptions}</select></div>
        <div><label for="grantDocument">Document</label><select id="grantDocument" name="document" required disabled><option value="">Choose an employee first</option></select>
          <p class="small muted" id="grantHint">Only the documents this employee cannot open yet are listed.</p></div>
        <div><label for="grantReason">Why</label><textarea id="grantReason" name="reason" maxlength="1000" placeholder="e.g. joined the Finance team"></textarea></div>
        <div class="row"><span class="spacer"></span><button class="button ok" type="submit">Give access</button></div>
      </form>
    </section>`);
}

// The documents the chosen employee cannot open yet: the ones they can are not worth giving.
async function loadGrantDocuments(user) {
  const select = $("#grantDocument");
  select.disabled = true;
  select.innerHTML = `<option value="">${user ? "Loading…" : "Choose an employee first"}</option>`;
  if (!user) return;
  const answer = await api("GET", `/admin/employees/${encodeURIComponent(user)}/documents`);
  if ($("#grantUser")?.value !== user) return;  // another employee was chosen meanwhile
  if (answer.status !== 200) { select.innerHTML = '<option value="">Could not load documents</option>'; toast(errorText(answer), "no"); return; }
  const documents = answer.data.documents;
  select.innerHTML = documents.length
    ? '<option value="">Choose…</option>' + documents.map((d) =>
        `<option value="${esc(d.id)}">${esc(d.title)} · ${esc(titled(d.department))}, ${esc(d.classification)}</option>`).join("")
    : '<option value="">This employee can open every document already</option>';
  select.disabled = !documents.length;
}

async function grant(form) {
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const answer = await api("POST", "/admin/grants", { user: form.user.value, document: form.document.value, reason: form.reason.value.trim() || null });
  button.disabled = false;
  if (answer.status !== 201) { toast(errorText(answer), "no"); return; }
  const request = answer.data.request;
  if (request.status === "already_granted") { toast("The employee could read this document already."); return; }
  flash = `<div class="notice ok"><h3>Access given</h3>
    <p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></div><br>`;
  location.hash = `#/admin/request/${request.id}`;
}

// --- admin: suggested access (A) -------------------------------------------------------------------

// Access Corax's model expects but nobody granted yet: most of the people most like this employee can
// open the document, and the request would look normal. Only admins see this list.
async function viewSuggestions(mine) {
  const answer = await api("GET", "/admin/suggestions");
  if (answer.status === 0) return;
  if (answer.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(answer))}</div>`); return; }
  const rows = answer.data.suggestions.map((s) => `
    <article class="request">
      <div class="stack">
        <div><b>${esc(s.user_name)}</b> <span class="muted small">${esc(titled(s.user_role))}, ${esc(titled(s.user_department))}</span></div>
        <div><span class="muted small">may need</span> <b>${esc(s.document_title)}</b> ${levelBadge(s.document_classification)}
          <span class="small muted">${esc(titled(s.document_department))}</span></div>
        <p class="small">${s.peers.with_access} of the ${s.peers.of} people most like them can open it.</p>
      </div>
      <div class="actions">
        <button class="button ok small" type="button" data-action="give-suggested" data-user="${esc(s.user)}" data-document="${esc(s.object)}">Give access</button>
        <button class="button ghost small" type="button" data-action="dismiss" data-user="${esc(s.user)}" data-document="${esc(s.object)}">Dismiss</button>
      </div>
    </article>`).join("");
  render(mine, `
    <div class="page-head"><div><h1>Suggested access</h1>
      <p>Access Corax expects but nobody has given yet: most of the people most like this employee can open the document. The employee does not see this list. Nothing is given until you choose.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <section class="card">${rows || '<p class="empty">No suggestions right now.</p>'}</section>`);
}

async function giveSuggested(user, document, button) {
  button.disabled = true;
  const answer = await api("POST", "/admin/grants", { user, document, reason: "suggested by Corax" });
  if (answer.status !== 201) { button.disabled = false; toast(errorText(answer), "no"); return; }
  flash = `<div class="notice ok"><h3>Access given</h3><p>Decide below whether people in the same situation get it too.</p></div><br>`;
  location.hash = `#/admin/request/${answer.data.request.id}`;
}

async function dismissSuggestion(user, document, button) {
  button.disabled = true;
  const answer = await api("POST", "/admin/suggestions/dismiss", { user, document });
  if (answer.status === 200) { toast("Dismissed."); route(); } else { button.disabled = false; toast(errorText(answer), "no"); }
}

// --- requests for a whole unit (C) ------------------------------------------------------------------

const UNIT_STATUS = { pending: ["warn", "Pending"], handled: ["ok", "Answered"], rejected: ["no", "Rejected"] };
const unitBadge = (status) => {
  const [kind, label] = UNIT_STATUS[status] || ["", status];
  return `<span class="badge ${kind}"><span class="dot"></span>${esc(label)}</span>`;
};

// The employee asks for documents of a unit without knowing which: they choose the unit from a list
// (never typed, never a title) and say why. The admin decides which documents, if any.
async function viewUnits(mine) {
  const [units, requests] = await Promise.all([api("GET", "/units"), api("GET", "/unit-requests")]);
  if (units.status === 0) return;
  if (units.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(units))}</div>`); return; }
  const options = units.data.units.map((u) => `<option value="${esc(u)}">${esc(titled(u))}</option>`).join("");
  const mineList = (requests.data?.requests || []).map((r) => `
    <article class="request"><div>
      <h3>${esc(titled(r.unit))} ${unitBadge(r.status)}</h3>
      <p class="small muted">#${r.id} · sent ${esc(ago(r.created_at))}${r.decided_at ? ` · answered ${esc(ago(r.decided_at))}` : ""}</p>
      ${r.status === "handled" ? `<p>${r.given} document${r.given === 1 ? "" : "s"} shared with you. <a href="#/shared">Shared with me</a></p>` : ""}
      ${r.note ? `<p class="small muted">Note: ${esc(r.note)}</p>` : ""}
    </div></article>`).join("");
  render(mine, `
    <div class="page-head"><div><h1>Ask for a unit</h1>
      <p>Need documents of another unit but do not know which? Choose the unit and say what you need. An admin decides what to share with you.</p></div></div>
    <section class="card">
      <form data-form="unit-request" class="stack">
        <div><label for="unit">Unit</label><select id="unit" name="unit" required>${options}</select></div>
        <div><label for="unitReason">What do you need it for?</label><textarea id="unitReason" name="reason" maxlength="1000" placeholder="e.g. the grant budget of my program"></textarea></div>
        <div class="row"><span class="spacer"></span><button class="button" type="submit">Send</button></div>
      </form>
    </section>
    <section class="card"><h2>Your unit requests</h2>${mineList || '<p class="empty">None yet.</p>'}</section>`);
}

async function requestUnit(form) {
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const answer = await api("POST", "/unit-requests", { unit: form.unit.value, reason: form.reason.value.trim() || null });
  button.disabled = false;
  if (answer.status === 201) { toast("Sent: an admin will decide."); route(); } else toast(errorText(answer), "no");
}

async function viewUnitRequests(mine) {
  const answer = await api("GET", "/admin/unit-requests");
  if (answer.status === 0) return;
  if (answer.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(answer))}</div>`); return; }
  const rows = answer.data.requests.map((r) => `
    <article class="request">
      <div class="stack">
        <div><b>${esc(r.user_name)}</b> <span class="muted small">${esc(titled(r.user_role))}, ${esc(titled(r.user_department))}</span></div>
        <div><span class="muted small">asks for documents of</span> <b>${esc(titled(r.unit))}</b> ${unitBadge(r.status)}</div>
        ${r.reason ? `<p class="reason">“${esc(r.reason)}”</p>` : ""}
      </div>
      <div class="actions">${r.status === "pending" ? `<a class="button small" href="#/unit-requests/${r.id}">Decide</a>` : ""}</div>
    </article>`).join("");
  render(mine, `
    <div class="page-head"><div><h1>Unit requests</h1><p>Employees who need documents of a unit but do not know which ones.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <section class="card">${rows || '<p class="empty">No unit requests.</p>'}</section>`);
}

async function viewUnitRequest(mine, id) {
  const answer = await api("GET", `/admin/unit-requests/${id}/documents`);
  if (answer.status === 0) return;
  const back = '<a href="#/unit-requests" class="small">← Unit requests</a>';
  if (answer.status !== 200) { render(mine, `${back}<div class="card notice warn">${esc(errorText(answer))}</div>`); return; }
  const { request, documents, warning } = answer.data;
  const rows = documents.map((d) => `
    <tr><td><input type="checkbox" name="documents" value="${esc(d.object)}"></td>
      <td><b>${esc(d.title)}</b> ${levelBadge(d.classification)}</td>
      <td class="num">${d.peers.with_access} of ${d.peers.of}</td>
      <td class="num">${Number(d.risk).toFixed(2)}</td></tr>`).join("");
  render(mine, `${back}
    <div class="page-head"><div><h1>${esc(request.user_name)} asks for ${esc(titled(request.unit))}</h1>
      <p>${esc(titled(request.user_role))}, ${esc(titled(request.user_department))}</p></div></div>
    ${request.reason ? `<section class="card"><p class="reason">“${esc(request.reason)}”</p></section>` : ""}
    ${warning ? `<div class="notice warn"><p>${esc(warning)}</p></div><br>` : ""}
    <section class="card">
      <form data-form="unit-grant" data-id="${request.id}" class="stack">
        <p class="muted">The unit's documents this employee cannot open yet, ranked by Corax: the ones most of the people like them can open first. Tick the ones to give. The employee never sees this list.</p>
        ${rows ? `<table class="candidates"><thead><tr><th></th><th>Document</th><th class="num">People like them who can open it</th><th class="num">How unusual (0–1)</th></tr></thead><tbody>${rows}</tbody></table>`
          : '<p class="empty">Nothing in this unit that the employee cannot open already.</p>'}
        <div class="row"><span class="spacer"></span>
          <button class="button ghost" type="button" data-action="reject-unit" data-id="${request.id}">Reject</button>
          <button class="button ok" type="submit">Give the ticked documents</button></div>
      </form>
    </section>`);
}

async function grantUnit(form) {
  const documents = [...form.querySelectorAll("input[name=documents]:checked")].map((box) => box.value);
  if (!documents.length) { toast("Tick at least one document, or reject.", "no"); return; }
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const answer = await api("POST", `/admin/unit-requests/${form.dataset.id}/grant`, { documents });
  button.disabled = false;
  if (answer.status !== 200) { toast(errorText(answer), "no"); return; }
  toast(`Given: ${documents.length} document${documents.length === 1 ? "" : "s"}. Each one is now under Access requests to decide on people in the same situation.`);
  location.hash = "#/admin/granted";
}

async function rejectUnit(id, button) {
  const note = prompt("Note for the employee (optional)") ?? null;
  button.disabled = true;
  const answer = await api("POST", `/admin/unit-requests/${id}/reject`, { note: note || null });
  if (answer.status === 200) { toast("Rejected."); location.hash = "#/unit-requests"; } else { button.disabled = false; toast(errorText(answer), "no"); }
}

// --- admin: access granted by appeals -------------------------------------------------------------

// Names for the admin's pages: employee id -> name, document id -> title. Read once after signing in
// (admins see every employee and document); before that, or for an unknown id, the short id is shown.
let directory = null;
async function loadDirectory() {
  if (directory) return directory;
  const [people, documents] = await Promise.all([api("GET", "/admin/employees"), api("GET", "/documents")]);
  if (people.status !== 200 || documents.status !== 200) return null;
  directory = {
    people: new Map(people.data.employees.map((e) => [e.id, e.name])),
    documents: new Map(documents.data.documents.map((d) => [d.id, d.title])),
  };
  return directory;
}
// "Mia Chen (E012)"; a document's title already carries its id: "Release plan (D004)"
const personName = (id) => directory?.people.get(id) ? `${directory.people.get(id)} (${short(id)})` : short(id);
const documentName = (id) => directory?.documents.get(id) || short(id);

// who gains or gained access to what, from Corax's grouped list ({users, by_user: [{user, objects}]})
const peopleList = (access, limit = 8) => `
  <p class="small"><b>${access.users}</b> ${access.users === 1 ? "person" : "people"}, <b>${access.objects}</b> document${access.objects === 1 ? "" : "s"}:</p>
  <ul class="small">${access.by_user.slice(0, limit).map((u) => `<li><b>${esc(personName(u.user))}</b>: ${u.objects.map((o) => esc(documentName(o))).join(", ")}</li>`).join("")}
    ${access.users > limit ? `<li class="muted">and ${access.users - limit} more</li>` : ""}</ul>`;

async function showWho(appealId, candidate) {
  showModal(`${modalHead(`Suggestion #${candidate}`)}<p class="muted">Asking Corax…</p>`);
  const [answer] = await Promise.all([api("GET", `/corax/appeals/${encodeURIComponent(appealId)}/candidates/${candidate}`), loadDirectory()]);
  if (!$("#modal")) return;
  const body = answer.status === 200
    ? `<p>${esc(answer.data.description)}</p>${scopeIndicators(answer.data.scope)}
       <h3>Who would get access</h3>${peopleList(answer.data.affected, 50)}
       <p class="small muted">Nothing is written until you apply it.</p>`
    : `<div class="notice warn"><p>${esc(errorText(answer))}</p></div>`;
  $(".modal", $("#modal")).innerHTML = modalHead(`Suggestion #${candidate}`) + body;
}

// Every rule and exception from an approved request still in effect: who approved it, who gained
// access, and every time that access was used since (GET /corax/rules).
async function viewRules(mine) {
  const [rules, requests] = await Promise.all([api("GET", "/corax/rules"), api("GET", "/admin/access-requests"), loadDirectory()]);
  if (rules.status === 0) return;
  if (rules.status !== 200) { render(mine, `<div class="card notice warn">${esc(errorText(rules))}</div>`); return; }
  const requestOf = new Map((requests.data?.requests || []).filter((r) => r.appeal_id).map((r) => [r.appeal_id, r]));
  const card = (e) => {
    const r = requestOf.get(e.appeal);
    const used = e.summary.findIndex((line) => line.startsWith("Used") || line.startsWith("Not used"));
    const uses = (e.uses || []).map((u) =>
      `<li>${esc(new Date(u.at).toLocaleString())}: <b>${esc(personName(u.user))}</b> opened ${esc(documentName(u.object))}</li>`).join("");
    const revoke = r ? `<button class="button danger small" type="button" data-action="${e.kind === "rule" ? "revoke" : "revoke-all"}" data-request="${r.id}">Revoke</button>` : "";
    return `<article class="request">
      <div class="stack">
        <h3>${esc(e.description)} <span class="badge ${e.kind === "rule" ? "accent" : ""}">${e.kind === "rule" ? "for a group" : "one person"}</span></h3>
        <p class="small muted">${esc(e.summary[1])}${r ? ` · request <a href="#/admin/request/${r.id}">#${r.id}</a>` : ""} · ${esc(e.appeal)}</p>
        ${e.file_missing ? '<div class="notice warn"><p>This access was removed outside Corax, so nobody recorded who did it.</p></div>' : ""}
        <div><h4>Gained access</h4>${peopleList(e.access)}</div>
        <div><h4>${esc(e.summary[used])}</h4>${uses ? `<ul class="small">${uses}</ul>` : ""}</div>
      </div>
      <div class="actions">${revoke}</div>
    </article>`;
  };
  render(mine, `
    <div class="page-head"><div><h1>Access granted</h1>
      <p>Every rule and exception an admin approved that is still in effect: who gained access, and every time that access was used since. Revoking deletes the rule and records who did it.</p></div>
      <button class="button ghost" type="button" data-action="refresh">Refresh</button></div>
    <section class="card">${rules.data.length ? rules.data.map(card).join("") : '<p class="empty">No access granted through requests yet.</p>'}</section>`);
}

async function revoke(requestId, everything, button) {
  const what = everything ? "the rule and the employee's own access" : "the rule for people in the same situation";
  if (!confirm(`Take back ${what}? It stops working at once.`)) return;
  button.disabled = true;
  const answer = await api("POST", `/admin/access-requests/${requestId}/revoke`, { exception: everything });
  if (answer.status === 200) { toast(`Revoked: ${what}.`); route(); return; }
  button.disabled = false;
  toast(answer.status === 409 ? "Nothing of this request is still in effect." : errorText(answer), "no");
}

// --- routing and events ---------------------------------------------------------------------------

const ROUTES = [
  [/^#\/login$/, viewLogin],
  [/^#\/documents$/, viewDocuments],
  [/^#\/documents\/([\w-]+)$/, viewDocument],
  [/^#\/shared$/, viewShared],
  [/^#\/requests$/, viewMyRequests],
  [/^#\/rules$/, viewRules],
  [/^#\/grant$/, viewGrant],
  [/^#\/suggestions$/, viewSuggestions],
  [/^#\/units$/, viewUnits],
  [/^#\/unit-requests$/, viewUnitRequests],
  [/^#\/unit-requests\/(\d+)$/, viewUnitRequest],
  [/^#\/admin(?:\/(pending|granted|decided|all))?$/, viewAdmin],
  [/^#\/admin\/request\/(\d+)$/, viewAdminRequest],
];

async function route() {
  const hash = location.hash || "#/";
  const signedIn = session.valid();
  if (!signedIn && hash !== "#/login") { session.clear(); location.replace("#/login"); return; }
  if (signedIn && ["#/", "#/login", "#"].includes(hash)) {
    location.replace(session.user.kind === "admin" ? "#/admin" : "#/documents");
    return;
  }
  closeModal();
  renderShell();
  const mine = ++ticket;
  for (const [pattern, view] of ROUTES) {
    const match = hash.match(pattern);
    if (match) {
      if (!app().innerHTML) app().innerHTML = '<p class="muted">Loading…</p>';
      await view(mine, ...match.slice(1).filter((part) => part !== undefined));
      return;
    }
  }
  render(mine, '<div class="card empty">Page not found. <a href="#/documents">Documents</a></div>');
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) {
    if (event.target.id === "modal") closeModal();
    return;
  }
  const { action, id, request, candidate, user, appeal, document: doc } = target.dataset;
  if (action === "close-modal") closeModal();
  else if (action === "fill-account") { $("#username").value = user; $("#password").value = "corax-demo"; $("#password").focus(); }
  else if (action === "preview") preview(id);
  else if (action === "refresh") route();
  else if (action === "approve") approve(id, target);
  else if (action === "reject") askReject(id);
  else if (action === "apply") confirmPattern(request, Number(candidate), false);
  else if (action === "ack") confirmPattern(request, Number(candidate), true);
  else if (action === "keep-exception") confirmPattern(request, null, false);
  else if (action === "who") showWho(appeal, Number(candidate));
  else if (action === "revoke") revoke(request, false, target);
  else if (action === "revoke-all") revoke(request, true, target);
  else if (action === "give-suggested") giveSuggested(user, doc, target);
  else if (action === "dismiss") dismissSuggestion(user, doc, target);
  else if (action === "reject-unit") rejectUnit(id, target);
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-form]");
  if (!form) return;
  event.preventDefault();
  if (form.dataset.form === "login") signIn(form);
  else if (form.dataset.form === "request-access") requestAccess(form);
  else if (form.dataset.form === "reject") reject(form);
  else if (form.dataset.form === "grant") grant(form);
  else if (form.dataset.form === "unit-request") requestUnit(form);
  else if (form.dataset.form === "unit-grant") grantUnit(form);
});

document.addEventListener("input", (event) => {
  const key = event.target.dataset?.filter;
  if (!key) return;
  filters[key] = event.target.type === "checkbox" ? event.target.checked : event.target.value.trim();
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => loadDocuments(ticket), key === "q" ? 250 : 0);
});

document.addEventListener("change", (event) => {
  if (event.target.id === "grantUser") loadGrantDocuments(event.target.value);
});

document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });
$("#signOut").addEventListener("click", () => signOut());
window.addEventListener("hashchange", route);
route();
