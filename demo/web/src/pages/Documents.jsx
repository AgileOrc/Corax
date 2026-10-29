import { useEffect, useState } from "react";

import { api } from "../api.js";
import { LevelBadge } from "../components/badges.jsx";
import { DocRow, Empty } from "../components/DocRow.jsx";
import { Modal } from "../components/Modal.jsx";
import { Button, inputClass, Notice, PageHead } from "../components/ui.jsx";
import { errorText, LEVELS, place, titled } from "../format.js";
import { forgetOnSignOut } from "../session.js";
import { sharedWithMe } from "../shared.js";
import { useSession } from "../SessionContext.jsx";

const NO_FILTERS = { q: "", department: "", classification: "", mine: false };
let kept = NO_FILTERS;
let departments = null;
forgetOnSignOut(() => { kept = NO_FILTERS; departments = null; });

export default function Documents() {
  const { user } = useSession();
  const admin = user.kind === "admin";
  const [filters, setFilters] = useState(kept);
  const [units, setUnits] = useState(departments);
  const [found, setFound] = useState(null);
  const [fresh, setFresh] = useState(0);
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    let current = true;
    if (!departments) {
      api("GET", "/documents").then((all) => {
        if (all.status === 200 && current) {
          departments = [...new Set(all.data.documents.map((d) => d.department))].sort();
          setUnits(departments);
        }
      });
    }
    if (!admin) sharedWithMe().then((shared) => { if (current && shared) setFresh(shared.fresh.length); });
    return () => { current = false; };
  }, [admin]);

  useEffect(() => {
    kept = filters;
    let current = true;
    const timer = setTimeout(async () => {
      const query = new URLSearchParams();
      for (const key of ["q", "department", "classification"]) if (filters[key]) query.set(key, filters[key]);
      const answer = await api("GET", `/documents?${query}`);
      if (!current || answer.status === 0) return;
      setFound(answer.status === 200 ? { documents: answer.data.documents } : { error: errorText(answer) });
    }, filters.q ? 250 : 0);
    return () => { current = false; clearTimeout(timer); };
  }, [filters.q, filters.department, filters.classification]);  // "mine" filters what is already here

  const set = (key) => (event) => setFilters((f) => ({ ...f, [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value }));
  const documents = found?.documents?.filter((d) => !filters.mine || d.in_my_projects);

  return (
    <>
      {fresh > 0 && (
        <div className="mb-4">
          <Notice kind="ok" title={`${fresh} new document${fresh === 1 ? " was" : "s were"} shared with you`}>
            <p>An admin approved access for people in your situation. <a href="#/shared">See them under Shared with me</a>.</p>
          </Notice>
        </div>
      )}
      <PageHead title="Documents">
        {admin
          ? "Every document, to give access. Reading documents is for employees."
          : <>The documents you can open. Need something else? Ask for it from its link, or <a href="#/units">ask for a unit</a>.</>}
      </PageHead>
      <div>
        <form role="search" onSubmit={(e) => e.preventDefault()}
              className="grid grid-cols-1 items-end gap-2.5 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className="sm:col-span-2 lg:col-span-1">
            <Label htmlFor="q">Search</Label>
            <input id="q" className={inputClass} placeholder="Title or id, e.g. D057" value={filters.q} onChange={set("q")} />
          </div>
          <div>
            <Label htmlFor="department">Department</Label>
            <select id="department" className={inputClass} value={filters.department} onChange={set("department")}>
              <option value="">All</option>
              {(units || []).map((d) => <option key={d} value={d}>{titled(d)}</option>)}
            </select>
          </div>
          <div>
            <Label htmlFor="classification">Classification</Label>
            <select id="classification" className={inputClass} value={filters.classification} onChange={set("classification")}>
              <option value="">All</option>
              {LEVELS.map((l) => <option key={l} value={l}>{titled(l)}</option>)}
            </select>
          </div>
          {admin ? <div /> : (
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input type="checkbox" checked={filters.mine} onChange={set("mine")} /> My projects
            </label>
          )}
        </form>
        {documents && <p className="mt-3 text-[13px] text-muted">{documents.length} document{documents.length === 1 ? "" : "s"}</p>}
        {!found ? <Empty>Loading…</Empty>
          : found.error ? <Empty>{found.error}</Empty>
          : documents.length === 0 ? <Empty>No documents match.</Empty>
          : (
            <ul>
              {documents.map((d) => (
                <DocRow key={d.id} doc={d} tags={d.in_my_projects ? ["Your project"] : []}
                        actions={admin ? null : <>
                          <Button variant="ghost" size="sm" onClick={() => setPreview(d.id)} className="font-medium!">Preview</Button>
                          <Button size="sm" href={`#/documents/${d.id}`} className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!">Open</Button>
                        </>} />
              ))}
            </ul>
          )}
      </div>
      {preview && <Preview id={preview} onClose={() => setPreview(null)} />}
    </>
  );
}

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;

function Preview({ id, onClose }) {
  const [answer, setAnswer] = useState(null);
  useEffect(() => {
    let current = true;
    api("GET", `/documents/${encodeURIComponent(id)}/summary`).then((a) => { if (current) setAnswer(a); });
    return () => { current = false; };
  }, [id]);

  return (
    <Modal title="Preview" onClose={onClose}>
      {!answer ? <p className="text-muted">Asking Corax…</p>
        : answer.status === 200 ? (
          <>
            <h3 className="font-semibold">{answer.data.title}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
              <LevelBadge level={answer.data.classification} />
              <span>{titled(answer.data.department)}</span>
              <span>Stored at {place(answer.data.site, answer.data.region)}</span>
            </div>
            <div className="mt-3.5 whitespace-pre-wrap rounded-lg border border-line bg-panel-2 p-4">{answer.data.summary}</div>
          </>
        )
        : answer.status === 403 ? <Notice kind="no" title="Corax blocked this preview"><p>You cannot preview this document.</p></Notice>
        : <Notice kind="warn"><p>{errorText(answer)}</p></Notice>}
    </Modal>
  );
}
