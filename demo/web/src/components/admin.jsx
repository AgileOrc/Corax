// What the admin's pages share: who asks, how far a rule reaches, who gains access, and the dialogs
// to reject or take access back.
import { useState } from "react";

import { api } from "../api.js";
import { documentName, personName } from "../directory.js";
import { errorText, initials, place, short, titled } from "../format.js";
import { LevelBadge } from "./badges.jsx";
import { Modal } from "./Modal.jsx";
import { useToast } from "./Toasts.jsx";
import { Badge, Button, inputClass } from "./ui.jsx";

export const TierBadge = ({ tier }) => tier ? <Badge kind={tier === "small" ? "ok" : "warn"}>{tier === "small" ? "few people" : "many people"}</Badge> : null;

export function Person({ r }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid size-[34px] flex-none place-items-center rounded-full bg-accent-soft text-[13px] font-bold text-accent">{initials(r.user_name)}</span>
      <div>
        <b>{r.user_name}</b> <span className="text-[13px] text-muted">{short(r.user_id)}</span>
        <div className="text-[13px] text-muted">{titled(r.user_role)}, {titled(r.user_department)}{r.user_site ? ` · ${place(r.user_site, r.user_region)}` : ""}</div>
      </div>
    </div>
  );
}

// The document of a request, with its details
export function RequestedDocument({ r, label = "asks for" }) {
  return (
    <div>
      <span className="text-[13px] text-muted">{label}</span>{" "}
      <b>{r.document_title}</b> <span className="text-[13px] text-muted">{short(r.document_id)}</span>{" "}
      <LevelBadge level={r.document_classification} />{" "}
      <span className="text-[13px] text-muted">{titled(r.document_department)} · stored at {place(r.document_site, r.document_region)}</span>
    </div>
  );
}

export function ScopeIndicators({ scope }) {
  const items = [
    [scope.users, "people"],
    [scope.pairs, "new accesses (one person, one document)"],
    [scope.mean_risk == null ? "–" : Number(scope.mean_risk).toFixed(2), "how unusual, on average (0 normal, 1 very unusual)"],
  ];
  return (
    <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
      {items.map(([value, label]) => (
        <div key={label} className="rounded-lg border border-line px-3 py-2.5">
          <b className="block text-xl tabular-nums">{value}</b>
          <span className="text-xs text-muted">{label}</span>
        </div>
      ))}
    </div>
  );
}

// who gains or gained access to what, from Corax's grouped list ({users, objects, by_user: [{user, objects}]})
export function PeopleList({ access, limit = 8 }) {
  return (
    <div className="text-[13px]">
      <p><b>{access.users}</b> {access.users === 1 ? "person" : "people"}, <b>{access.objects}</b> document{access.objects === 1 ? "" : "s"}:</p>
      <ul className="mt-1 list-disc pl-5">
        {access.by_user.slice(0, limit).map((u) => (
          <li key={u.user}><b>{personName(u.user)}</b>: {u.objects.map(documentName).join(", ")}</li>
        ))}
        {access.users > limit && <li className="text-muted">and {access.users - limit} more</li>}
      </ul>
    </div>
  );
}

// A dialog with an optional note, for a rejection; onSubmit(note) returns true when it went through
export function NoteDialog({ title, action, onSubmit, onClose }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    if (!(await onSubmit(note.trim() || null))) setBusy(false);
  }
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit}>
        <label htmlFor="note" className="mb-1 block text-[13px] font-medium text-muted">Note for the employee (optional)</label>
        <textarea id="note" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" type="submit" disabled={busy}>{action}</Button>
        </div>
      </form>
    </Modal>
  );
}

// Takes back the rule of a request (everything: also the employee's own exception), after asking
export function RevokeButton({ requestId, everything, label, variant = "danger", onDone }) {
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const what = everything ? "the rule and the employee's own access" : "the rule for people in the same situation";

  async function revoke() {
    setBusy(true);
    const answer = await api("POST", `/admin/access-requests/${requestId}/revoke`, { exception: everything });
    setBusy(false);
    setAsking(false);
    if (answer.status === 200) { toast(`Revoked: ${what}.`); onDone(); return; }
    toast(answer.status === 409 ? "Nothing of this request is still in effect." : errorText(answer), "no");
  }

  return (
    <>
      <Button variant={variant} size="sm" onClick={() => setAsking(true)}>{label}</Button>
      {asking && (
        <Modal title="Take access back?" onClose={() => setAsking(false)}>
          <p>Take back {what}? It stops working at once.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAsking(false)}>Cancel</Button>
            <Button variant="danger" onClick={revoke} disabled={busy}>Take back</Button>
          </div>
        </Modal>
      )}
    </>
  );
}

// A row of a list on the admin's pages: the details on the left, the actions on the right
export function Row({ children, actions }) {
  return (
    <article className="grid grid-cols-1 gap-3.5 border-b border-line px-1 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="space-y-2">{children}</div>
      {actions && <div className="flex flex-row flex-wrap items-start gap-1.5 sm:flex-col sm:items-stretch">{actions}</div>}
    </article>
  );
}
