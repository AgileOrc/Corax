import { useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Modal } from "../../components/Modal.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, Notice } from "../../components/ui.jsx";
import { errorText, ref, titled } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

// A unit request: the unit's documents this employee cannot open yet, ranked by Corax. The admin
// ticks the ones to give, or rejects.
export function UnitDecide({ r, onClose, onReject }) {
  const toast = useToast();
  const [answer] = useLoad(() => api("GET", `/admin/unit-requests/${r.id}/documents`));
  const [ticked, setTicked] = useState(new Set());
  const [busy, setBusy] = useState(false);

  const tick = (object) => setTicked((all) => {
    const next = new Set(all);
    if (next.has(object)) next.delete(object); else next.add(object);
    return next;
  });

  async function give(event) {
    event.preventDefault();
    if (!ticked.size) { toast("Select at least one document, or reject.", "no"); return; }
    setBusy(true);
    const given = await api("POST", `/admin/unit-requests/${r.id}/grant`, { documents: [...ticked] });
    setBusy(false);
    if (given.status !== 200) { toast(errorText(given), "no"); return; }
    toast(`${ticked.size} document${ticked.size === 1 ? "" : "s"} granted.`);
    onClose();
    go("#/admin/granted");
  }

  const { documents, warning } = answer?.status === 200 ? answer.data : {};
  return (
    <Modal title={`${r.user_name} asks for ${titled(r.unit)}`} onClose={onClose} width="max-w-4xl">
      <p className="text-sm text-muted">{ref("unit", r.id)} · {titled(r.user_role)}, {titled(r.user_department)}</p>
      {r.reason && <p className="mt-2 text-sm">“{r.reason}”</p>}
      {!answer || answer.status === 0 ? <Empty>Loading…</Empty>
        : answer.status !== 200 ? <div className="mt-4"><Notice kind="warn"><p>{errorText(answer)}</p></Notice></div>
        : (
          <form onSubmit={give} className="mt-4">
            {warning && <div className="mb-4"><Notice kind="warn"><p>{warning}</p></Notice></div>}
            <p className="text-sm text-muted">Select the documents to grant. Hidden from the employee.</p>
            {documents.length === 0 ? <Empty>Nothing in this unit that the employee cannot open already.</Empty> : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                      <th className="px-1.5 py-2" /><th className="px-1.5 py-2">Document</th>
                      <th className="px-1.5 py-2 text-right" title="How many of the employee's closest peers can open it">Peer access</th>
                      <th className="px-1.5 py-2 text-right" title="From 0 (usual) to 1 (unusual)">Risk score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((d) => (
                      <tr key={d.object} className="border-b border-line">
                        <td className="px-1.5 py-2.5">
                          <input type="checkbox" aria-label={`Give ${d.title}`} checked={ticked.has(d.object)} onChange={() => tick(d.object)} />
                        </td>
                        <td className="px-1.5 py-2.5"><b>{d.title}</b> <LevelBadge level={d.classification} /></td>
                        <td className="px-1.5 py-2.5 text-right tabular-nums">{d.peers.with_access}/{d.peers.of}</td>
                        <td className="px-1.5 py-2.5 text-right tabular-nums">{Number(d.risk).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-4 flex justify-end gap-4">
              <Button variant="ghost" className="font-medium!" onClick={onReject}>Reject</Button>
              <Button type="submit" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" disabled={busy}>Grant selected{ticked.size ? ` (${ticked.size})` : ""}</Button>
            </div>
          </form>
        )}
    </Modal>
  );
}

// Reject a unit request with an optional note; returns true when it went through
export function useRejectUnit(id) {
  const toast = useToast();
  return async function reject(note) {
    const done = await api("POST", `/admin/unit-requests/${id}/reject`, { note });
    if (done.status !== 200) { toast(errorText(done), "no"); return false; }
    toast(`Request ${ref("unit", id)} rejected.`);
    go("#/admin/decided");
    return true;
  };
}
