import { useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { NoteDialog } from "../../components/admin.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, Notice, PageHead } from "../../components/ui.jsx";
import { errorText, titled } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

const Back = () => <a href="#/unit-requests" className="text-[13px]">← Unit requests</a>;

// A unit request: the unit's documents this employee cannot open yet, ranked by Corax. The admin
// ticks the ones to give, or rejects.
export default function UnitRequest({ params: [id] }) {
  const toast = useToast();
  const [answer] = useLoad(() => api("GET", `/admin/unit-requests/${id}/documents`));
  const [ticked, setTicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  if (!answer || answer.status === 0) return <><Back /><Empty>Loading…</Empty></>;
  if (answer.status !== 200) return <><Back /><Notice kind="warn"><p>{errorText(answer)}</p></Notice></>;
  const { request, documents, warning } = answer.data;

  const tick = (object) => setTicked((all) => {
    const next = new Set(all);
    if (next.has(object)) next.delete(object); else next.add(object);
    return next;
  });

  async function give(event) {
    event.preventDefault();
    if (!ticked.size) { toast("Tick at least one document, or reject.", "no"); return; }
    setBusy(true);
    const given = await api("POST", `/admin/unit-requests/${request.id}/grant`, { documents: [...ticked] });
    setBusy(false);
    if (given.status !== 200) { toast(errorText(given), "no"); return; }
    toast(`Given: ${ticked.size} document${ticked.size === 1 ? "" : "s"}. Each one is now under Access requests to decide on people in the same situation.`);
    go("#/admin/granted");
  }

  async function reject(note) {
    const done = await api("POST", `/admin/unit-requests/${request.id}/reject`, { note });
    if (done.status !== 200) { toast(errorText(done), "no"); return false; }
    toast("Rejected.");
    go("#/unit-requests");
    return true;
  }

  return (
    <>
      <Back />
      <PageHead title={`${request.user_name} asks for ${titled(request.unit)}`}>
        {titled(request.user_role)}, {titled(request.user_department)}
      </PageHead>
      {request.reason && <p className="mb-4 text-sm">“{request.reason}”</p>}
      {warning && <div className="mb-4"><Notice kind="warn"><p>{warning}</p></Notice></div>}
      <form onSubmit={give}>
        <p className="text-muted">The unit's documents this employee cannot open yet, ranked by Corax: the ones most of the people like them can open first. Tick the ones to give. The employee never sees this list.</p>
        {documents.length === 0 ? <Empty>Nothing in this unit that the employee cannot open already.</Empty> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-1.5 py-2" /><th className="px-1.5 py-2">Document</th>
                  <th className="px-1.5 py-2 text-right">People like them who can open it</th>
                  <th className="px-1.5 py-2 text-right">How unusual (0–1)</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr key={d.object} className="border-b border-line">
                    <td className="px-1.5 py-2.5">
                      <input type="checkbox" aria-label={`Give ${d.title}`} checked={ticked.has(d.object)} onChange={() => tick(d.object)} />
                    </td>
                    <td className="px-1.5 py-2.5"><b>{d.title}</b> <LevelBadge level={d.classification} /></td>
                    <td className="px-1.5 py-2.5 text-right tabular-nums">{d.peers.with_access} of {d.peers.of}</td>
                    <td className="px-1.5 py-2.5 text-right tabular-nums">{Number(d.risk).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setRejecting(true)}>Reject</Button>
          <Button variant="ok" type="submit" disabled={busy}>Give the ticked documents</Button>
        </div>
      </form>
      {rejecting && <NoteDialog title="Reject the unit request" action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
    </>
  );
}
