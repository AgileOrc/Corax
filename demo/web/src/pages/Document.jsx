import { useState } from "react";

import { api } from "../api.js";
import { Badge, Button, inputClass, Notice, PageHead } from "../components/ui.jsx";
import { LevelBadge } from "../components/badges.jsx";
import { ago, errorText, place, project, titled } from "../format.js";
import { useSession } from "../SessionContext.jsx";
import { useToast } from "../components/Toasts.jsx";
import { useLoad } from "../useLoad.js";

const Back = () => <a href="#/documents" className="text-[13px]">← Documents</a>;

// One document: its content when Corax allows it, else a way to ask for access
export default function Document({ params: [id] }) {
  const { user } = useSession();
  const [opened, setOpened] = useState(null);  // a message after a request that opened it at once
  const [page, reload] = useLoad(async () => {
    const answer = await api("GET", `/documents/${encodeURIComponent(id)}`);
    if (answer.status !== 403 && answer.status !== 404) return { answer };
    // the employee's own requests for it, to show one that is still pending
    const mine = user.kind === "employee" ? await api("GET", "/access-requests") : null;
    const requests = mine?.status === 200 ? mine.data.requests.filter((r) => r.document_id === id) : [];
    return { answer, pending: requests.find((r) => r.status === "pending") };
  });

  if (!page || page.answer.status === 0) return <><Back /><p className="mt-4 text-muted">Loading…</p></>;
  const { answer, pending } = page;

  if (answer.status === 200) {
    const d = answer.data;
    return (
      <>
        <Back />
        {opened && <div className="my-3">{opened}</div>}
        <PageHead title={d.title} actions={<Badge kind="ok" dot>Corax allowed it</Badge>}>
          <span className="font-mono">{d.id}</span>
        </PageHead>
        <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div>
            <h2 className="text-lg font-semibold">Content</h2>
            <div className="mt-3.5 whitespace-pre-wrap rounded-lg border border-line bg-panel-2 p-4">{d.content}</div>
          </div>
          <div><Details doc={d} /></div>
        </div>
      </>
    );
  }

  if (answer.status !== 403 && answer.status !== 404) {
    return <><Back /><div className="mt-3"><Notice kind="warn"><p>{errorText(answer)}</p></Notice></div></>;
  }
  return (
    <>
      <Back />
      <PageHead title="No access" actions={<Badge kind="no" dot>Denied by Corax</Badge>} />
      <div>
        <Notice kind="no" title="You do not have access to this document">
          <p>If someone shared this link with you, you can ask an admin for access. Need documents of a whole unit instead? <a href="#/units">Ask for a unit</a>.</p>
        </Notice>
        <div className="mt-4">
          {user.kind !== "employee"
            ? <p className="text-muted">Admins do not read documents here; they review the employees' requests.</p>
            : pending
              ? (
                <Notice kind="info" title="Your request is pending">
                  <p>Request #{pending.id}, sent {ago(pending.created_at)}. You can follow it under <a href="#/requests">My requests</a>.</p>
                </Notice>
              )
              : <AskForAccess id={id} onOpened={(message) => { setOpened(message); reload(); }} />}
        </div>
      </div>
    </>
  );
}

function Details({ doc }) {
  const rows = [
    ["Classification", <LevelBadge level={doc.classification} />],
    ["Department", titled(doc.department)],
    ["Projects", (doc.projects || []).map(project).join(", ")],
    ["Stored at", place(doc.site, doc.region)],
  ];
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map(([name, value]) => (
          <tr key={name} className="border-b border-line last:border-b-0">
            <td className="w-2/5 py-1.5 align-top text-muted">{name}</td>
            <td className="py-1.5 align-top">{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AskForAccess({ id, onOpened }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const answer = await api("POST", `/access-requests/${encodeURIComponent(id)}`, { reason: reason.trim() || null });
    setBusy(false);
    if (answer.status !== 201) {
      toast(answer.status === 409 ? "You already have a pending request for this document." : errorText(answer), "no");
      return;
    }
    // granted at once: show the document itself. The employee only needs to know it opens, not the
    // rule behind it (that is for admins, under Access granted).
    const status = answer.data.status;
    if (status === "granted" || status === "generalised") onOpened(<Notice kind="ok" title="Access granted"><p>You can read this document now.</p></Notice>);
    else if (status === "already_granted") onOpened(<Notice kind="info" title="You can read it already" />);
    else setSent(true);
  }

  if (sent) {
    return (
      <Notice kind="ok" title="Request sent">
        <p>Your request is waiting for an admin. Follow it under <a href="#/requests">My requests</a>.</p>
      </Notice>
    );
  }
  return (
    <form onSubmit={submit}>
      <label htmlFor="reason" className="mb-1 block text-[13px] font-medium text-muted">Why do you need it?</label>
      <textarea id="reason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                placeholder="e.g. I coordinate all engineering projects" value={reason} onChange={(e) => setReason(e.target.value)} />
      <Button type="submit" className="mt-3" disabled={busy}>Request access</Button>
    </form>
  );
}
