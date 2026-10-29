import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { DocRow, Empty } from "../../components/DocRow.jsx";
import { Modal } from "../../components/Modal.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, inputClass, Notice, PageHead } from "../../components/ui.jsx";
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
  const [user, setUser] = useState(null);
  const [closed, setClosed] = useState(null);  // the documents the chosen employee cannot open yet
  const [filters, setFilters] = useState(NO_FILTERS);
  const [giving, setGiving] = useState(null);

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
      Every document in the store. Choose an employee to give them one they cannot open yet.
    </PageHead>
  );
  if (!page || page.people.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (page.people.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.people)}</p></Notice></>;

  const employees = page.people.data.employees;
  const catalog = page.catalog.data?.documents || [];
  const q = filters.q.trim().toLowerCase();
  const matches = !user && q ? employees.filter((e) => `${e.name} ${short(e.id)} ${e.role} ${e.department}`.toLowerCase().replace(/_/g, " ").includes(q)).slice(0, 6) : [];

  const departments = [...new Set(catalog.map((d) => d.department))].sort();
  const documents = user ? closed : catalog;
  const shown = (documents || []).filter((d) =>
    (!filters.department || d.department === filters.department)
    && (!filters.classification || d.classification === filters.classification)
    && (!q || `${d.title} ${short(d.id)}`.toLowerCase().includes(q)));
  const set = (key) => (event) => setFilters((f) => ({ ...f, [key]: event.target.value }));

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
          {matches.length > 0 && (
            <ul className="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-line bg-panel shadow-card">
              <li className="px-4 pt-2 text-xs font-semibold uppercase tracking-wide text-muted">Employees</li>
              {matches.map((e) => (
                <li key={e.id}>
                  <button type="button" onClick={() => { setUser(e); setFilters((f) => ({ ...f, q: "" })); }}
                          className="w-full cursor-pointer px-4 py-2.5 text-left hover:bg-ink/5">
                    <EmployeeLine e={e} />
                  </button>
                </li>
              ))}
            </ul>
          )}
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
      {documents && <p className="mt-3 text-[13px] text-muted">{shown.length} document{shown.length === 1 ? "" : "s"}{user ? ` ${user.name} cannot open yet` : ""}</p>}
      {user && closed === null ? <Empty>Loading…</Empty>
        : user && closed.length === 0 ? <Empty>This employee can open every document already.</Empty>
        : shown.length === 0 ? <Empty>No documents match.</Empty>
        : (
          <ul>
            {shown.map((d) => (
              <DocRow key={d.id} doc={d} link={false} onOpen={user ? () => setGiving(d) : undefined}
                      actions={user && <Button size="sm" className={HOVER} onClick={() => setGiving(d)}>Give access</Button>} />
            ))}
          </ul>
        )}
      {giving && <GiveDialog user={user} doc={giving} onClose={() => setGiving(null)} />}
    </>
  );
}

// name (id) | role - department | place
function EmployeeLine({ e, label }) {
  return (
    <span className="text-sm text-muted">
      {label && `${label} `}<b className="font-semibold text-ink">{e.name}</b> ({short(e.id)}) | {titled(e.role)} - {titled(e.department)}
      {e.site ? ` | ${place(e.site, e.region)}` : ""}
    </span>
  );
}

// the reason popup; giving starts a request that is already approved
function GiveDialog({ user, doc, onClose }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
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
        <div>
          <div className="flex flex-wrap items-center gap-2"><b>{doc.title}</b> <LevelBadge level={doc.classification} /></div>
          <EmployeeLine e={user} label="to" />
        </div>
        <div>
          <Label htmlFor="grantReason">Reason</Label>
          <textarea id="grantReason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                    placeholder="e.g. joined the Finance team" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="flex justify-end gap-4">
          <Button variant="ghost" className="font-medium! border-ink/25!" onClick={onClose}>Cancel</Button>
          <Button type="submit" className={HOVER} disabled={busy}>Give access</Button>
        </div>
      </form>
    </Modal>
  );
}

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;
