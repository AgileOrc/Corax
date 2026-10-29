import { useState } from "react";

import { api } from "../../api.js";
import { Empty } from "../../components/DocRow.jsx";
import { Modal } from "../../components/Modal.jsx";
import { RevokeButton, Row } from "../../components/admin.jsx";
import { Badge, Button, inputClass, Notice, PageHead } from "../../components/ui.jsx";
import { documentName, loadDirectory, personName } from "../../directory.js";
import { errorText, ref } from "../../format.js";
import { useLoad } from "../../useLoad.js";

const HOVER = "hover:text-accent! hover:bg-transparent! hover:border-accent/80!";
const KIND = { rule: "Rule", exception: "Exception" };
const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

// Every rule and exception from an approved request still in effect (GET /corax/rules), and a log of
// every time that access was used since
export default function Rules() {
  const [page, reload] = useLoad(async () => {
    const [rules, requests] = await Promise.all([api("GET", "/corax/rules"), api("GET", "/admin/access-requests"), loadDirectory()]);
    return { rules, requests };
  });
  const [tab, setTab] = useState("granted");
  const [details, setDetails] = useState(null);
  const head = (
    <PageHead title="Access granted">
      Rules and exceptions approved through Corax that are still in effect, and how they were used.
    </PageHead>
  );
  if (!page || page.rules.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (page.rules.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.rules)}</p></Notice></>;

  const requestOf = new Map((page.requests.data?.requests || []).filter((r) => r.appeal_id).map((r) => [r.appeal_id, r]));
  const entries = page.rules.data.map((e) => ({ ...e, request: requestOf.get(e.appeal) }));
  const uses = entries.flatMap((e) => (e.uses || []).map((u) => ({ ...u, entry: e })))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)));

  return (
    <>
      {head}
      {/* tabs */}
      <nav className="mb-2 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
        {[["granted", "Granted", entries.length], ["activity", "Activity", uses.length]].map(([key, label, n]) => (
          <button key={key} type="button" onClick={() => setTab(key)}
                  className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-3.5 py-2 font-semibold ${key === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}>
            {label} <Badge>{n}</Badge>
          </button>
        ))}
      </nav>
      {tab === "granted"
        ? (entries.length === 0 ? <Empty>No access granted through requests yet.</Empty>
          : entries.map((e) => <GrantRow key={`${e.appeal}/${e.kind}`} e={e} onDetails={() => setDetails(e)} onDone={reload} />))
        : <Activity uses={uses} />}
      {details && <Details e={details} onClose={() => setDetails(null)} />}
    </>
  );
}

// title of an entry: the rule's sentence, or who may read what for an exception
function title(e) {
  if (e.kind === "rule") return e.description;
  const [u] = e.access.by_user;
  return u ? `${documentName(u.objects[0])} for ${personName(u.user)}` : e.description;
}

// granted row
function GrantRow({ e, onDetails, onDone }) {
  const r = e.request;
  const n = e.uses?.length || 0;
  return (
    <Row actions={
      <div className="flex gap-4">
        <Button variant="ghost" size="sm" className="font-medium!" onClick={onDetails}>Details</Button>
        {r && <RevokeButton requestId={r.id} everything={e.kind !== "rule"} label="Revoke" variant="primary" className={HOVER} onDone={onDone} />}
      </div>
    }>
      <div className="flex flex-wrap items-center gap-2">
        <Badge kind={e.kind === "rule" ? "accent" : ""}>{KIND[e.kind]}</Badge>
        <button type="button" onClick={onDetails} className="cursor-pointer text-left font-semibold text-ink underline-offset-4 hover:underline">{title(e)}</button>
      </div>
      <p className="text-[13px] text-muted">
        {e.approved_by} · {when(e.at)}{r && <> · <a href={`#/admin/request/${r.id}`}>{ref("document", r.id)}</a></>}
        {" "}· {e.access.users} {e.access.users === 1 ? "person" : "people"} · {e.access.objects} document{e.access.objects === 1 ? "" : "s"} · used {n}×
      </p>
      {e.file_missing && <Notice kind="warn"><p>This access was removed outside Corax, so nobody recorded who did it.</p></Notice>}
    </Row>
  );
}

// details popup
function Details({ e, onClose }) {
  return (
    <Modal title={KIND[e.kind]} titleClass="text-lg font-medium" headClass="mb-1" onClose={onClose}>
      <p className="mb-1 text-xl font-semibold">{title(e)}</p>
      <p className="mb-4 text-sm text-muted">Approved by {e.approved_by} · {when(e.at)}{e.request ? ` · ${ref("document", e.request.id)}` : ""}</p>
      <p className="mb-2 text-sm text-muted">{e.access.users} {e.access.users === 1 ? "person" : "people"}, {e.access.objects} document{e.access.objects === 1 ? "" : "s"}</p>
      <ul className="space-y-1">
        {e.access.by_user.map((u) => (
          <li key={u.user} className="text-[13px]">
            <b className="font-semibold">{personName(u.user)}</b>: <span className="text-muted">{u.objects.map(documentName).join(", ")}</span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

// activity log
function Activity({ uses }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const text = q.trim().toLowerCase();
  const shown = uses.filter((u) =>
    (!kind || u.entry.kind === kind)
    && (!text || `${personName(u.user)} ${documentName(u.object)}`.toLowerCase().includes(text)));

  return (
    <>
      <form role="search" onSubmit={(e) => e.preventDefault()}
            className="mt-4 grid grid-cols-1 items-end gap-2.5 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:w-3/4">
        <div>
          <Label htmlFor="q">Search</Label>
          <input id="q" className={inputClass} autoComplete="off" placeholder="Employee or document" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="kind">Granted by</Label>
          <select id="kind" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="rule">Rule</option>
            <option value="exception">Exception</option>
          </select>
        </div>
      </form>
      <p className="mt-3 text-[13px] text-muted">{shown.length} use{shown.length === 1 ? "" : "s"}</p>
      {uses.length === 0 ? <Empty>Nobody has used this access yet.</Empty>
        : shown.length === 0 ? <Empty>No uses match.</Empty>
        : (
          <ul>
            {shown.map((u, i) => (
              <li key={i} className="grid grid-cols-1 gap-1 border-b border-line px-1 py-3 last:border-b-0 sm:grid-cols-[11rem_minmax(0,1fr)_auto] sm:items-center sm:gap-4">
                <span className="text-[13px] text-muted tabular-nums">{when(u.at)}</span>
                <span className="text-sm"><b className="font-semibold">{personName(u.user)}</b> <span className="text-muted">opened</span> {documentName(u.object)}</span>
                <span className="text-[13px] text-muted">
                  via {KIND[u.entry.kind]}{u.entry.request ? <> · <a href={`#/admin/request/${u.entry.request.id}`}>{ref("document", u.entry.request.id)}</a></> : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
    </>
  );
}

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;
