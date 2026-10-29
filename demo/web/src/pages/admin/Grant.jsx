import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { DocRow, Empty } from "../../components/DocRow.jsx";
import { Modal } from "../../components/Modal.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Badge, Button, inputClass, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { errorText, LEVELS, place, short, titled } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

const HOVER = "hover:text-accent! hover:bg-transparent! hover:border-accent/80!";
const NO_FILTERS = { q: "", department: "", classification: "" };

// Every document in the store. With an employee chosen: the ones they cannot open yet, to give one
// (a new team member, a change of role). Corax then suggests the same access for people in the same situation.
export default function Grant() {
  const toast = useToast();
  const [page] = useLoad(async () => {
    const [people, catalog] = await Promise.all([api("GET", "/admin/employees"), api("GET", "/documents")]);
    return { people, catalog };
  });
  const [tab, setTab] = useState("documents");
  const [user, setUser] = useState(null);
  const [closed, setClosed] = useState(null);  // the documents the chosen employee cannot open yet
  const [filters, setFilters] = useState(NO_FILTERS);
  const [giving, setGiving] = useState(null);
  const [holders, setHolders] = useState(null);
  const [holdings, setHoldings] = useState(null);

  useEffect(() => {
    setClosed(null);
    if (!user) return;
    let current = true;
    api("GET", `/admin/employees/${encodeURIComponent(user.id)}/documents`).then((answer) => {
      if (!current) return;
      if (answer.status === 200) setClosed(answer.data.documents);
      else { setClosed([]); toast(errorText(answer), "no"); }
    });
    return () => { current = false; };
  }, [user, toast]);

  const head = (
    <PageHead title="Give access">
      Every document in the store. Click a document to give it to someone, or search an employee to see what they cannot open yet.
    </PageHead>
  );
  if (!page || page.people.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (page.people.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.people)}</p></Notice></>;

  const employees = page.people.data.employees;
  const catalog = page.catalog.data?.documents || [];
  const q = filters.q.trim().toLowerCase();
  const searching = !user && q !== "";

  const departments = [...new Set(catalog.map((d) => d.department))].sort();
  const documents = user ? closed : catalog;
  const shown = (documents || []).filter((d) =>
    (!filters.department || d.department === filters.department)
    && (!filters.classification || d.classification === filters.classification)
    && (!q || `${d.title} ${short(d.id)}`.toLowerCase().includes(q)));
  const people = employees.filter((e) =>
    (!filters.department || e.department === filters.department)
    && (!q || `${e.name} ${short(e.id)} ${e.role} ${e.department}`.toLowerCase().replace(/_/g, " ").includes(q)));
  const set = (key) => (event) => setFilters((f) => ({ ...f, [key]: event.target.value }));
  const choose = (e) => { setUser(e); setFilters((f) => ({ ...f, q: "" })); };

  const documentList = (
    <ul>
      {shown.map((d) => (
        <DocRow key={d.id} doc={d} link={false} onOpen={() => setGiving(d)}
                actions={user
                  ? <Button size="sm" className={HOVER} onClick={() => setGiving(d)}>Give access</Button>
                  : <Button variant="ghost" size="sm" className="font-medium!" onClick={() => setHolders(d)}>Members</Button>} />
      ))}
    </ul>
  );
  const employeeList = (
    <ul>
      {people.map((e) => (
        <EmployeeRow key={e.id} e={e} onOpen={() => choose(e)}
                     action={<Button variant="ghost" size="sm" className="font-medium!" onClick={() => setHoldings(e)}>Permissions</Button>} />
      ))}
    </ul>
  );
  const count = (n, what) => <p className="mt-3 text-[13px] text-muted">{n} {what}{n === 1 ? "" : "s"}</p>;

  return (
    <>
      {head}
      {/* chosen employee */}
      {user && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-panel px-4 py-2.5 lg:w-3/4">
          <EmployeeLine e={user} label="giving access to" />
          <Button variant="ghost" size="sm" className="font-medium!" onClick={() => { setUser(null); setFilters(NO_FILTERS); }}>Change</Button>
        </div>
      )}
      {/* search and filters */}
      <form role="search" onSubmit={(e) => e.preventDefault()}
            className="grid grid-cols-1 items-end gap-2.5 sm:grid-cols-2 lg:w-3/4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Label htmlFor="q">Search</Label>
          <input id="q" className={inputClass} autoComplete="off" value={filters.q} onChange={set("q")}
                 placeholder={user ? "Title or id, e.g. D057" : "Employee, or document title or id"} />
        </div>
        <div>
          <Label htmlFor="department">Department</Label>
          <select id="department" className={inputClass} value={filters.department} onChange={set("department")}>
            <option value="">All</option>
            {departments.map((d) => <option key={d} value={d}>{titled(d)}</option>)}
          </select>
        </div>
        <div>
          <Label htmlFor="classification">Classification</Label>
          <select id="classification" className={inputClass} value={filters.classification} onChange={set("classification")}>
            <option value="">All</option>
            {LEVELS.map((l) => <option key={l} value={l}>{titled(l)}</option>)}
          </select>
        </div>
      </form>
      {/* tabs */}
      {!user && !searching && (
        <nav className="mt-5 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
          {[["documents", "Documents", shown.length], ["employees", "Employees", people.length]].map(([key, label, n]) => (
            <button key={key} type="button" onClick={() => setTab(key)}
                    className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-3.5 py-2 font-semibold ${key === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}>
              {label} <Badge>{n}</Badge>
            </button>
          ))}
        </nav>
      )}
      {user ? (
        <>
          {closed && count(shown.length, "document") }
          {closed === null ? <Empty>Loading…</Empty>
            : closed.length === 0 ? <Empty>This employee can open every document already.</Empty>
            : shown.length === 0 ? <Empty>No documents match.</Empty>
            : documentList}
        </>
      ) : searching ? (
        people.length + shown.length === 0 ? <Empty>No results.</Empty> : (
          <>
            {count(people.length + shown.length, "result")}
            {people.length > 0 && employeeList}
            {shown.length > 0 && documentList}
          </>
        )
      ) : tab === "employees" ? (
        people.length === 0 ? <Empty>No employee matches.</Empty> : employeeList
      ) : (
        shown.length === 0 ? <Empty>No documents match.</Empty> : documentList
      )}
      {giving && <GiveDialog user={user} doc={giving} onClose={() => setGiving(null)} />}
      {holders && <WhoHasAccess doc={holders} onClose={() => setHolders(null)} />}
      {holdings && <HasAccessTo e={holdings} onClose={() => setHoldings(null)} />}
    </>
  );
}

// name (id) | role - department | place
function EmployeeLine({ e, label, className = "text-sm" }) {
  return (
    <span className={`${className} text-muted`}>
      {label && `${label} `}<b className="font-semibold text-ink">{e.name}</b> ({short(e.id)}) | {titled(e.role)} - {titled(e.department)}
      {e.site ? ` | ${place(e.site, e.region)}` : ""}
    </span>
  );
}

// employee row
function EmployeeRow({ e, onOpen, action }) {
  return (
    <li className="grid grid-cols-1 items-center gap-3 border-b border-line px-1 py-3.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div>
        <button type="button" onClick={onOpen} className="cursor-pointer text-left font-semibold text-ink underline-offset-4 hover:underline">{e.name}</button>
        <p className="mt-1 text-[13px] text-muted">{short(e.id)} | {titled(e.role)} - {titled(e.department)}{e.site ? ` | ${place(e.site, e.region)}` : ""}</p>
      </div>
      <div className="flex gap-3">{action}</div>
    </li>
  );
}

// members popup
function WhoHasAccess({ doc, onClose }) {
  const [answer] = useLoad(() => api("GET", `/admin/documents/${encodeURIComponent(doc.id)}/employees`));
  const list = answer?.status === 200 ? answer.data.with_access : null;
  return (
    <Modal title="Members" titleClass="text-lg font-medium" headClass="mb-1" onClose={onClose}>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xl"><b>{doc.title}</b> <LevelBadge level={doc.classification} /></div>
      {!answer || answer.status === 0 ? <p className="text-muted">Loading…</p>
        : !list ? <Notice kind="warn"><p>{errorText(answer)}</p></Notice>
        : list.length === 0 ? <p className="text-muted">No employee can open it.</p>
        : (
          <>
            <p className="mb-2 text-sm text-muted">{list.length} employee{list.length === 1 ? "" : "s"}</p>
            <ul className="space-y-1">{list.map((e) => <li key={e.id}><EmployeeLine e={e} className="text-[13px] font-medium" /></li>)}</ul>
          </>
        )}
    </Modal>
  );
}

// permissions popup
function HasAccessTo({ e, onClose }) {
  const [answer] = useLoad(() => api("GET", `/admin/employees/${encodeURIComponent(e.id)}/documents`));
  const list = answer?.status === 200 ? answer.data.open : null;
  return (
    <Modal title="Permissions" titleClass="text-lg font-medium" headClass="mb-1" onClose={onClose}>
      <div className="mb-4 text-muted">
        <p className="text-2xl"><b className="font-semibold text-ink">{e.name}</b> ({short(e.id)})</p>
        <p className="text-base">{titled(e.role)} - {titled(e.department)}{e.site ? ` | ${place(e.site, e.region)}` : ""}</p>
      </div>
      {!answer || answer.status === 0 ? <p className="text-muted">Loading…</p>
        : !list ? <Notice kind="warn"><p>{errorText(answer)}</p></Notice>
        : list.length === 0 ? <p className="text-muted">They cannot open any document.</p>
        : (
          <>
            <p className="mb-2 text-sm text-muted">{list.length} document{list.length === 1 ? "" : "s"}</p>
            <ul className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
              {list.map((d) => <li key={d.id} className="flex flex-wrap items-center gap-2 text-[13px] font-normal"><span>{d.title}</span> <LevelBadge level={d.classification} /></li>)}
            </ul>
          </>
        )}
    </Modal>
  );
}

// the reason popup; giving starts a request that is already approved
function GiveDialog({ user: given, doc, onClose }) {
  const toast = useToast();
  const [user, setUser] = useState(given);
  const [who, setWho] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer] = useLoad(() => given ? Promise.resolve(null) : api("GET", `/admin/documents/${encodeURIComponent(doc.id)}/employees`));
  const employees = answer?.status === 200 ? answer.data.employees : [];
  const text = who.trim().toLowerCase();
  const matches = text ? employees.filter((e) => `${e.name} ${short(e.id)} ${e.role} ${e.department}`.toLowerCase().replace(/_/g, " ").includes(text)).slice(0, 6) : [];

  async function submit(event) {
    event.preventDefault();
    if (!user) { toast("Choose an employee first.", "no"); return; }
    setBusy(true);
    const answer = await api("POST", "/admin/grants", { user: user.id, document: doc.id, reason: reason.trim() || null });
    setBusy(false);
    if (answer.status !== 201) { toast(errorText(answer), "no"); return; }
    const request = answer.data.request;
    if (request.status === "already_granted") { toast("The employee could read this document already."); onClose(); return; }
    setFlash(<Notice kind="accent" title="Access given"><p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></Notice>);
    go(`#/admin/request/${request.id}`);
  }

  return (
    <Modal title="Give access" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2"><b>{doc.title}</b> <LevelBadge level={doc.classification} /></div>
        {user ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <EmployeeLine e={user} label="to" />
            {!given && <Button variant="ghost" size="sm" className="font-medium! border-ink/25!" onClick={() => setUser(null)}>Change</Button>}
          </div>
        ) : (
          <div className="relative">
            <Label htmlFor="grantWho">Employee</Label>
            <input id="grantWho" className={inputClass} autoComplete="off" disabled={!answer} placeholder={!answer ? "Loading employees…" : `${employees.length} employees cannot open it yet`}
                   value={who} onChange={(e) => setWho(e.target.value)} />
            {text && (
              <ul className="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-line bg-panel shadow-card">
                {matches.length === 0 ? <li className="px-4 py-2.5 text-sm text-muted">No employee who cannot open it matches.</li> : matches.map((e) => (
                  <li key={e.id}>
                    <button type="button" onClick={() => { setUser(e); setWho(""); }} className="w-full cursor-pointer px-4 py-2.5 text-left hover:bg-ink/5">
                      <EmployeeLine e={e} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div>
          <Label htmlFor="grantReason">Reason</Label>
          <textarea id="grantReason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                    placeholder="e.g. joined the Finance team" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="flex justify-end gap-4">
          <Button variant="ghost" className="font-medium! border-ink/25!" onClick={onClose}>Cancel</Button>
          <Button type="submit" className={HOVER} disabled={busy || !user}>Give access</Button>
        </div>
      </form>
    </Modal>
  );
}

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;
