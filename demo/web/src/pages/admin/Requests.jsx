import { useState } from "react";

import { api } from "../../api.js";
import { StatusBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { NoteDialog, Person, RequestedDocument, Row, TierBadge } from "../../components/admin.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Badge, Button, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { ago, errorText, ruleText } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

const TABS = [
  ["pending", "Pending", (r) => r.status === "pending"],
  ["granted", "Your decision", (r) => r.status === "granted"],
  ["decided", "Decided", (r) => !["pending", "granted"].includes(r.status)],
  ["all", "All", () => true],
];

// Every access request waits for an admin: approve or reject, then decide on people in the same situation
export default function Requests({ params: [tab = "pending"] }) {
  const [answer, reload] = useLoad(() => api("GET", "/admin/access-requests"));
  const head = (
    <PageHead title="Access requests" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Every request waits for you. Approve to give the employee the document, then decide whether people in the same situation get it too.
    </PageHead>
  );
  if (!answer || answer.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (answer.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(answer)}</p></Notice></>;

  const all = answer.data.requests;
  const [, , keep] = TABS.find(([key]) => key === tab) || TABS[0];
  const shown = all.filter(keep);
  return (
    <>
      {head}
      <nav className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(([key, label, test]) => (
          <a key={key} href={`#/admin/${key}`}
             className={`-mb-px whitespace-nowrap border-b-2 px-3.5 py-2 font-semibold hover:no-underline ${key === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}>
            {label} <Badge>{all.filter(test).length}</Badge>
          </a>
        ))}
      </nav>
      {shown.length === 0 ? <Empty>Nothing here.</Empty> : shown.map((r) => <RequestRow key={r.id} r={r} onChange={reload} />)}
    </>
  );
}

function RequestRow({ r, onChange }) {
  const [rejecting, setRejecting] = useState(false);
  const approve = useApprove(r.id, onChange);
  const reject = useReject(r.id, onChange);
  const given = r.requested_by && r.requested_by !== r.user_id;
  return (
    <Row actions={<>
      {r.status === "pending" && <>
        <Button variant="ok" size="sm" onClick={approve}>Approve</Button>
        <Button variant="ghost" size="sm" onClick={() => setRejecting(true)}>Reject</Button>
      </>}
      {r.status === "granted" && <Button size="sm" href={`#/admin/request/${r.id}`}>Decide</Button>}
      <Button variant="ghost" size="sm" href={`#/admin/request/${r.id}`}>Details</Button>
    </>}>
      <Person r={r} />
      <RequestedDocument r={r} label={given ? `given by ${r.requested_by}:` : "asks for"} />
      {r.reason && <p className="text-sm">“{r.reason}”</p>}
      <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
        #{r.id} · {ago(r.created_at)} <StatusBadge status={r.status} />
        {r.rule_pattern && <> · {ruleText(r, r.rule_pattern)} <TierBadge tier={r.tier} /></>}
      </p>
      {rejecting && <NoteDialog title={`Reject request #${r.id}`} action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
    </Row>
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
      setFlash(<Notice kind="ok" title="Approved"><p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></Notice>);
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
    toast(`Request #${id} rejected.`);
    onChange();
    return true;
  };
}
