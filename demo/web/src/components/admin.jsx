// What the admin's pages share: who asks, how far a rule reaches, who gains access, and the dialogs
// to reject or take access back.
import { useState } from "react";

import { api } from "../api.js";
import { documentName, personName } from "../directory.js";
import { errorText, initials, place, short, titled } from "../format.js";
import { Modal } from "./Modal.jsx";
import { useToast } from "./Toasts.jsx";
import { Badge, Button, inputClass } from "./ui.jsx";

export const TierBadge = ({ tier }) => tier ? <Badge kind={tier === "small" ? "ok" : "warn"}>{tier === "small" ? "Narrow" : "Broad"}</Badge> : null;

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

// who asked: name (id) | role - department | place
export function Asker({ r, label = "requested by" }) {
  return (
    <p className="mt-1 text-sm text-muted">
      {label} <b className="font-semibold text-ink">{r.user_name}</b> ({short(r.user_id)}) | {titled(r.user_role)} - {titled(r.user_department)}
      {r.user_site ? ` | ${place(r.user_site, r.user_region)}` : ""}
    </p>
  );
}

// a title that opens the details
export const OpenTitle = ({ onClick, children }) => (
  <button type="button" onClick={onClick} className="cursor-pointer text-left font-bold text-ink underline-offset-4 hover:underline">{children}</button>
);

export function ScopeIndicators({ scope }) {
  const items = [
    [scope.users, "People", "People who would gain access"],
    [scope.pairs, "Grants", "New accesses: one person, one document"],
    [scope.mean_risk == null ? "–" : Number(scope.mean_risk).toFixed(2), "Risk", "Mean risk score, from 0 (usual) to 1 (unusual)"],
  ];
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {items.map(([value, label, hint]) => (
        <span key={label} title={hint} className="inline-flex items-baseline gap-1.5 rounded-full bg-accent-soft px-3.5 py-1.5">
          <b className="text-lg tabular-nums text-accent">{value}</b>
          <span className="text-[13px] text-muted">{label}</span>
        </span>
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
        <div className="mt-4 flex justify-end gap-4">
          <Button variant="ghost" className="font-medium! border-ink/25!" onClick={onClose}>Cancel</Button>
          <Button type="submit" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" disabled={busy}>{action}</Button>
        </div>
      </form>
    </Modal>
  );
}

// Takes back the rule of a request (everything: also the employee's own exception), after asking
export function RevokeButton({ requestId, everything, label, variant = "primary", className = "", onDone }) {
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
      <Button variant={variant} size="sm" className={className} onClick={() => setAsking(true)}>{label}</Button>
      {asking && (
        <Modal title="Revoke access?" onClose={() => setAsking(false)}>
          <p>Revoke {what}? This takes effect immediately.</p>
          <div className="mt-4 flex justify-end gap-4">
            <Button variant="ghost" className="font-medium! border-ink/25!" onClick={() => setAsking(false)}>Cancel</Button>
            <Button className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" onClick={revoke} disabled={busy}>Revoke</Button>
          </div>
        </Modal>
      )}
    </>
  );
}

// A row of a list on the admin's pages: the details on the left, the actions on the right
export function Row({ children, actions }) {
  return (
    <article className="grid grid-cols-1 gap-3.5 border-b border-line px-1 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="space-y-2">{children}</div>
      {actions && <div className="flex flex-row flex-wrap items-start gap-1.5 sm:flex-col sm:items-stretch">{actions}</div>}
    </article>
  );
}
