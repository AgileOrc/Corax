import { useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Asker, Row } from "../../components/admin.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, inputClass, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { errorText, place, titled } from "../../format.js";
import { go } from "../../router.js";
import { forgetOnSignOut } from "../../session.js";
import { useLoad } from "../../useLoad.js";

const HOVER = "hover:text-accent! hover:bg-transparent! hover:border-accent/80!";
const NO_FILTERS = { q: "", department: "", site: "" };
let kept = NO_FILTERS;
forgetOnSignOut(() => { kept = NO_FILTERS; });

// Access Corax's model expects but nobody granted yet: most of the people most like this employee can
// open the document, and the request would look normal. Only admins see this list.
export default function Suggestions() {
  const toast = useToast();
  const [answer, reload] = useLoad(() => api("GET", "/admin/suggestions"));
  const [busy, setBusy] = useState(null);
  const [filters, setFilters] = useState(kept);
  const set = (key) => (event) => setFilters((f) => { kept = { ...f, [key]: event.target.value }; return kept; });

  async function give(s) {
    setBusy(`${s.user}/${s.object}`);
    const given = await api("POST", "/admin/grants", { user: s.user, document: s.object, reason: "suggested by Corax" });
    setBusy(null);
    if (given.status !== 201) { toast(errorText(given), "no"); return; }
    setFlash(<Notice kind="accent" title="Access given"><p>Decide below whether people in the same situation get it too.</p></Notice>);
    go(`#/admin/request/${given.data.request.id}`);
  }

  async function dismiss(s) {
    setBusy(`${s.user}/${s.object}`);
    const done = await api("POST", "/admin/suggestions/dismiss", { user: s.user, document: s.object });
    setBusy(null);
    if (done.status === 200) { toast("Dismissed."); reload(); } else toast(errorText(done), "no");
  }

  const head = (
    <PageHead title="Suggested access">
      Access Corax expects but nobody has granted yet. Hidden from employees.
    </PageHead>
  );
  if (!answer || answer.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (answer.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(answer)}</p></Notice></>;

  const suggestions = answer.data.suggestions;
  const departments = [...new Set(suggestions.map((s) => s.user_department))].sort();
  const sites = [...new Map(suggestions.map((s) => [s.user_site, place(s.user_site, s.user_region)])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const q = filters.q.trim().toLowerCase();
  const shown = suggestions.filter((s) =>
    (!filters.department || s.user_department === filters.department)
    && (!filters.site || s.user_site === filters.site)
    && (!q || `${s.user_name} ${s.document_title}`.toLowerCase().includes(q)));

  return (
    <>
      {head}
      {/* filters */}
      <form role="search" onSubmit={(e) => e.preventDefault()}
            className="grid grid-cols-1 items-end gap-2.5 sm:grid-cols-2 lg:w-3/4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="sm:col-span-2 lg:col-span-1">
          <Label htmlFor="q">Search</Label>
          <input id="q" className={inputClass} placeholder="Employee or document" value={filters.q} onChange={set("q")} />
        </div>
        <div>
          <Label htmlFor="department">Department</Label>
          <select id="department" className={inputClass} value={filters.department} onChange={set("department")}>
            <option value="">All</option>
            {departments.map((d) => <option key={d} value={d}>{titled(d)}</option>)}
          </select>
        </div>
        <div>
          <Label htmlFor="site">Location</Label>
          <select id="site" className={inputClass} value={filters.site} onChange={set("site")}>
            <option value="">All</option>
            {sites.map(([site, label]) => <option key={site} value={site}>{label}</option>)}
          </select>
        </div>
      </form>
      <p className="mt-3 text-[13px] text-muted">{shown.length} suggestion{shown.length === 1 ? "" : "s"}</p>
      {suggestions.length === 0 ? <Empty>No suggestions right now.</Empty>
        : shown.length === 0 ? <Empty>No suggestions match.</Empty>
        : shown.map((s) => {
          const working = busy === `${s.user}/${s.object}`;
          return (
            <Row key={`${s.user}/${s.object}`} actions={
              <div className="flex gap-4">
                <Button variant="ghost" size="sm" className="font-medium!" disabled={working} onClick={() => dismiss(s)}>Dismiss</Button>
                <Button size="sm" className={HOVER} disabled={working} onClick={() => give(s)}>Give access</Button>
              </div>
            }>
              <div>
                <div className="flex flex-wrap items-center gap-2 text-lg">
                  <b>{s.document_title}</b>
                  <span className="text-sm text-muted">| {titled(s.document_department)} - stored at {place(s.document_site, s.document_region)}</span>
                  <LevelBadge level={s.document_classification} />
                </div>
                <Asker r={{ ...s, user_id: s.user }} label="suggested for" />
              </div>
              <p className="text-sm text-muted">{s.peers.with_access}/{s.peers.of} closest peers can open it.</p>
            </Row>
          );
        })}
    </>
  );
}

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;
