import { useState } from "react";

import { api } from "../api.js";
import { EmployeeBadge, LevelBadge, UnitBadge } from "../components/badges.jsx";
import { Empty } from "../components/DocRow.jsx";
import { Modal } from "../components/Modal.jsx";
import { useToast } from "../components/Toasts.jsx";
import { Badge, Button, inputClass, Notice, PageHead } from "../components/ui.jsx";
import { ago, errorText, ref, short, titled } from "../format.js";
import { useLoad } from "../useLoad.js";

const OPENS = ["granted", "generalised", "exception_only", "already_granted"];
const OUTCOME = (r) => r.kind === "unit"
  ? { pending: "pending", handled: "approved" }[r.status] || "rejected"
  : { pending: "pending", rejected: "rejected", revoked: "rejected" }[r.status] || "approved";
const TABS = [
  ["all", "All", () => true],
  ["pending", "Pending", (r) => OUTCOME(r) === "pending"],
  ["approved", "Approved", (r) => OUTCOME(r) === "approved"],
  ["rejected", "Rejected", (r) => OUTCOME(r) === "rejected"],
];
const HOVER ="hover:text-accent! hover:bg-transparent! hover:border-accent/80!";

// The documents and units the employee asked for, and what the admin decided: never how Corax decided
export default function MyRequests() {
  const [page, reload] = useLoad(async () => {
    const [documents, units] = await Promise.all([api("GET", "/access-requests"), api("GET", "/unit-requests")]);
    return { documents, units };
  });
  const [asking, setAsking] = useState(false);
  const [tab, setTab] = useState("all");

  const head = (
    <PageHead title="My requests" actions={<Button className={HOVER} onClick={() => setAsking(true)}>Ask for a unit</Button>}>
      Documents and units you asked for, and what the admin decided.
    </PageHead>
  );
  const dialog = asking && <AskForUnit onClose={() => setAsking(false)} onSent={() => { setAsking(false); reload(); }} />;
  if (!page || page.documents.status === 0) return <>{head}<Empty>Loading…</Empty>{dialog}</>;
  if (page.documents.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.documents)}</p></Notice>{dialog}</>;

  const requests = [
    ...page.documents.data.requests.map((r) => ({ ...r, kind: "document" })),
    ...(page.units.data?.requests || []).map((r) => ({ ...r, kind: "unit" })),
  ].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const [, , keep] = TABS.find(([key]) => key === tab);
  const shown = requests.filter(keep);

  return (
    <>
      {head}
      {/* tabs */}
      <nav className="mb-2 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
        {TABS.map(([key, label, test]) => (
          <button key={key} type="button" onClick={() => setTab(key)}
                  className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-3.5 py-2 font-semibold ${key === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}>
            {label} <Badge>{requests.filter(test).length}</Badge>
          </button>
        ))}
      </nav>
      {requests.length === 0
        ? <Empty>No requests yet. Ask for a document from its link, or ask for a unit.</Empty>
        : shown.length === 0 ? <Empty>Nothing here.</Empty>
        : shown.map((r) => r.kind === "unit" ? <UnitRow key={`unit-${r.id}`} r={r} /> : <DocumentRow key={`document-${r.id}`} r={r} />)}
      {dialog}
    </>
  );
}

// row: details on the left, status on the right
function RequestRow({ children, badge, sent, decided, action }) {
  return (
    <article className="grid grid-cols-1 gap-4 border-b border-line px-1 py-5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div>{children}</div>
      <div className="flex flex-col gap-1.5 sm:items-end sm:text-right">
        {badge}
        <p className="text-sm text-muted">sent {ago(sent)}</p>
        {decided && <p className="text-sm text-muted">{decided}</p>}
        {action && <div className="mt-1.5">{action}</div>}
      </div>
    </article>
  );
}

// document request
function DocumentRow({ r }) {
  return (
    <RequestRow badge={r.status !== "pending" && <EmployeeBadge status={r.status} />} sent={r.created_at} decided={r.decided_at && `decided ${ago(r.decided_at)}`}
                action={OPENS.includes(r.status) && <Button size="sm" href={`#/documents/${r.document_id}`} className={HOVER}>Open document</Button>}>
      <h3 className="text-lg font-semibold">
        <a href={`#/documents/${r.document_id}`} className="text-ink">{r.document_title || `Document ${short(r.document_id)}`}</a>
      </h3>
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-muted">
        {ref("document", r.id)}
        {r.document_classification && <> · <LevelBadge level={r.document_classification} /></>}
      </p>
      {r.reason && <p className="mt-1.5 text-[15px]">“{r.reason}”</p>}
      {r.note && <p className="mt-1 text-sm text-muted">Note: {r.note}</p>}
    </RequestRow>
  );
}

// unit request
function UnitRow({ r }) {
  return (
    <RequestRow badge={r.status !== "pending" && <UnitBadge status={r.status} />} sent={r.created_at} decided={r.decided_at && `answered ${ago(r.decided_at)}`}>
      <h3 className="text-lg font-semibold">{titled(r.unit)}</h3>
      <p className="mt-1 text-sm text-muted">{ref("unit", r.id)}</p>
      {r.reason && <p className="mt-1.5 text-[15px]">“{r.reason}”</p>}
      {r.status === "handled" && <p className="mt-1.5 text-[15px]">{r.given} document{r.given === 1 ? "" : "s"} shared with you. <a href="#/shared">Shared with me</a></p>}
      {r.note && <p className="mt-1 text-sm text-muted">Note: {r.note}</p>}
    </RequestRow>
  );
}

// ask for a unit popup
function AskForUnit({ onClose, onSent }) {
  const toast = useToast();
  const [answer] = useLoad(() => api("GET", "/units"));
  const [unit, setUnit] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const units = answer?.status === 200 ? answer.data.units : [];
  const chosen = unit || units[0] || "";

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const sent = await api("POST", "/unit-requests", { unit: chosen, reason: reason.trim() || null });
    setBusy(false);
    if (sent.status === 201) onSent(); else toast(errorText(sent), "no");
  }

  return (
    <Modal title="Ask for a unit" onClose={onClose}>
      <p className="mb-4 text-sm text-muted">Need documents of another unit but do not know which? Choose the unit and say what you need. An admin decides what to share with you.</p>
      {!answer || answer.status === 0 ? <p className="text-muted">Loading…</p>
        : answer.status !== 200 ? <Notice kind="warn"><p>{errorText(answer)}</p></Notice>
        : (
          <form onSubmit={submit}>
            <label htmlFor="unit" className="mb-1 block text-[13px] font-medium text-muted">Unit</label>
            <select id="unit" className={inputClass} value={chosen} onChange={(e) => setUnit(e.target.value)} required>
              {units.map((u) => <option key={u} value={u}>{titled(u)}</option>)}
            </select>
            <label htmlFor="unitReason" className="mb-1 mt-3 block text-[13px] font-medium text-muted">What do you need it for?</label>
            <textarea id="unitReason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                      placeholder="e.g. the grant budget of my program" value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="mt-4 flex justify-end"><Button type="submit" className={HOVER} disabled={busy}>Send</Button></div>
          </form>
        )}
    </Modal>
  );
}
