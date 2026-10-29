import { useState } from "react";

import { api } from "../../api.js";
import { LevelBadge, StatusBadge, UnitBadge } from "../../components/badges.jsx";
import { Modal } from "../../components/Modal.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Asker, NoteDialog, OpenTitle, Person, Row, TierBadge } from "../../components/admin.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Badge, Button, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { ago, errorText, place, ref, ruleText, short, titled } from "../../format.js";
import { go } from "../../router.js";
import { forgetOnSignOut } from "../../session.js";
import { useLoad } from "../../useLoad.js";
import { UnitDecide, useRejectUnit } from "./UnitRequest.jsx";

const TABS = [
  ["pending", "Pending", (r) => r.status === "pending"],
  ["granted", "Your decision", (r) => r.kind === "document" && r.status === "granted"],
  ["decided", "Decided", (r) => r.kind === "unit" ? r.status !== "pending" : !["pending", "granted"].includes(r.status)],
  ["all", "All", () => true],
];
const KINDS = [["all", "All"], ["document", "Documents"], ["unit", "Units"]];
let keptKind = "all";
forgetOnSignOut(() => { keptKind = "all"; });

// Every document and unit request waits for an admin
export default function Requests({ params: [tab = "pending"] }) {
  const [page, reload] = useLoad(async () => {
    const [documents, units] = await Promise.all([api("GET", "/admin/access-requests"), api("GET", "/admin/unit-requests")]);
    return { documents, units };
  });
  const [kind, setKind] = useState(keptKind);
  const head = (
    <PageHead title="Requests">
      Employees asking for a document or for documents of a unit. Approve a document, then decide whether people in the same situation get it too.
    </PageHead>
  );
  if (!page || page.documents.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (page.documents.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.documents)}</p></Notice></>;

  const all = [
    ...page.documents.data.requests.map((r) => ({ ...r, kind: "document" })),
    ...(page.units.data?.requests || []).map((r) => ({ ...r, kind: "unit" })),
  ].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const ofKind = all.filter((r) => kind === "all" || r.kind === kind);
  const [, , keep] = TABS.find(([key]) => key === tab) || TABS[0];
  const shown = ofKind.filter(keep);
  const choose = (key) => { keptKind = key; setKind(key); };

  return (
    <>
      {head}
      <div className="mb-4 flex flex-wrap items-end gap-3 border-b border-line">
        {/* tabs */}
        <nav className="flex gap-1 overflow-x-auto overflow-y-hidden">
          {TABS.map(([key, label, test]) => (
            <a key={key} href={`#/admin/${key}`}
               className={`whitespace-nowrap border-b-2 px-3.5 py-2 font-semibold hover:no-underline ${key === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}>
              {label} <Badge>{ofKind.filter(test).length}</Badge>
            </a>
          ))}
        </nav>
        {/* kind filter */}
        <div className="mb-2 ml-auto flex gap-1 rounded-lg border border-line p-0.5">
          {KINDS.map(([key, label]) => (
            <button key={key} type="button" onClick={() => choose(key)}
                    className={`cursor-pointer rounded-md px-2.5 py-1 text-sm font-medium transition ${key === kind ? "bg-accent-soft text-accent" : "text-muted hover:text-ink"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? <Empty>Nothing here.</Empty>
        : shown.map((r) => r.kind === "unit" ? <UnitRow key={`unit-${r.id}`} r={r} /> : <RequestRow key={`document-${r.id}`} r={r} onChange={reload} />)}
    </>
  );
}

// unit request
function UnitRow({ r }) {
  const [deciding, setDeciding] = useState(false);
  const [details, setDetails] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const reject = useRejectUnit(r.id);
  const pending = r.status === "pending";
  return (
    <Row actions={<>
      <When at={r.created_at} />
      {pending && <Button size="sm" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" onClick={() => setDeciding(true)}>Decide</Button>}
    </>}>
      <div>
        <div className="text-lg">
          <OpenTitle onClick={() => pending ? setDeciding(true) : setDetails(true)}>{titled(r.unit)} Documents</OpenTitle>
        </div>
        <Asker r={r} />
      </div>
      {r.reason && <p className="line-clamp-2 text-sm">“{r.reason}”</p>}
      <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
        {ref("unit", r.id)} {!pending && <UnitBadge status={r.status} />}
      </p>
      {deciding && <UnitDecide r={r} onClose={() => setDeciding(false)} onReject={() => { setDeciding(false); setRejecting(true); }} />}
      {details && <UnitDetails r={r} onClose={() => setDetails(false)} />}
      {rejecting && <NoteDialog title={`Reject request ${ref("unit", r.id)}`} action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
    </Row>
  );
}

function RequestRow({ r, onChange }) {
  const [rejecting, setRejecting] = useState(false);
  const [details, setDetails] = useState(false);
  const approve = useApprove(r.id, onChange);
  const reject = useReject(r.id, onChange);
  const given = r.requested_by && r.requested_by !== r.user_id;
  const pending = r.status === "pending";
  return (
    <Row actions={<>
      <When at={r.created_at} />
      {pending && (
        <div className="flex gap-4">
          <Button variant="ghost" size="sm" className="font-medium!" onClick={() => setRejecting(true)}>Reject</Button>
          <Button size="sm" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" onClick={approve}>Approve</Button>
        </div>
      )}
      {r.status === "granted" && <Button size="sm" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" href={`#/admin/request/${r.id}`}>Decide</Button>}
    </>}>
      <div>
        <div className="flex flex-wrap items-center gap-2 text-lg">
          <OpenTitle onClick={() => pending ? setDetails(true) : go(`#/admin/request/${r.id}`)}>{r.document_title}</OpenTitle>
          <span className="text-sm text-muted">| {titled(r.document_department)} - stored at {place(r.document_site, r.document_region)}</span>
          <LevelBadge level={r.document_classification} />
        </div>
        <Asker r={r} label={given ? `given by ${r.requested_by} to` : "requested by"} />
      </div>
      {r.reason && <p className="line-clamp-2 text-sm">“{r.reason}”</p>}
      <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
        {ref("document", r.id)} {!["pending", "granted"].includes(r.status) && <StatusBadge status={r.status} />}
        {r.rule_pattern && <> · {ruleText(r, r.rule_pattern)} <TierBadge tier={r.tier} /></>}
      </p>
      {details && <PendingDetails r={r} onClose={() => setDetails(false)} onApprove={approve} onReject={() => { setDetails(false); setRejecting(true); }} />}
      {rejecting && <NoteDialog title={`Reject request ${ref("document", r.id)}`} action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
    </Row>
  );
}

// sent time, above the buttons
const When = ({ at }) => <p className="text-right text-[13px] text-muted">{ago(at)}</p>;

// details popup of a decided unit request
function UnitDetails({ r, onClose }) {
  return (
    <Modal title={ref("unit", r.id)} onClose={onClose}>
      <div className="space-y-4">
        <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
          <UnitBadge status={r.status} /> sent {ago(r.created_at)}{r.decided_at ? ` · answered ${ago(r.decided_at)}` : ""}
        </p>
        <div><b>{r.user_name}</b> <span className="text-[13px] text-muted">{titled(r.user_role)}, {titled(r.user_department)}</span></div>
        <div><span className="text-[13px] text-muted">asks for documents of</span> <b>{titled(r.unit)}</b></div>
        {r.reason ? <p className="whitespace-pre-wrap text-sm">“{r.reason}”</p> : <p className="text-[13px] text-muted">No reason given.</p>}
        {r.status === "handled" && <p className="text-sm">{r.given} document{r.given === 1 ? "" : "s"} given.</p>}
        {r.note && <p className="text-sm text-muted">Note: {r.note}</p>}
      </div>
    </Modal>
  );
}

// details popup of a pending request; approving opens the request's page
function PendingDetails({ r, onClose, onApprove, onReject }) {
  return (
    <Modal title={ref("document", r.id)} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-muted">sent {ago(r.created_at)}</p>
        <Person r={r} />
        <div>
          <span className="text-[13px] text-muted">asks for</span>
          <div className="font-semibold">{r.document_title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
            <LevelBadge level={r.document_classification} />
            <span>{titled(r.document_department)}</span>
            <span>Stored at {place(r.document_site, r.document_region)}</span>
          </div>
        </div>
        {r.reason ? <p className="whitespace-pre-wrap text-sm">“{r.reason}”</p> : <p className="text-[13px] text-muted">No reason given.</p>}
        <div className="flex justify-end gap-4">
          <Button variant="ghost" className="font-medium!" onClick={onReject}>Reject</Button>
          <Button className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" onClick={onApprove}>Approve</Button>
        </div>
      </div>
    </Modal>
  );
}

// Approve a request: the employee can read the document; the admin goes on to decide on others
export function useApprove(id, onChange) {
  const toast = useToast();
  return async function approve(event) {
    const button = event?.currentTarget;
    if (button) button.disabled = true;
    const answer = await api("POST", `/admin/access-requests/${id}/approve`);
    if (answer.status !== 200) { if (button) button.disabled = false; toast(errorText(answer), "no"); return; }
    if (answer.data.request.status === "granted") {
      setFlash(<Notice kind="accent" title="Approved"><p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></Notice>);
      go(`#/admin/request/${id}`);
      onChange();
    } else {
      toast("The employee could read the document already.");
      onChange();
    }
  };
}

// Reject a request with an optional note; returns true when it went through
export function useReject(id, onChange) {
  const toast = useToast();
  return async function reject(note) {
    const answer = await api("POST", `/admin/access-requests/${id}/reject`, { note });
    if (answer.status !== 200) { toast(errorText(answer), "no"); return false; }
    toast(`Request ${ref("document", id)} rejected.`);
    onChange();
    return true;
  };
}
