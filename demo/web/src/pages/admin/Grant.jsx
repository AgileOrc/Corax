import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { Empty } from "../../components/DocRow.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, inputClass, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { errorText, titled } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

const Label = (props) => <label className="mb-1 mt-3 block text-[13px] font-medium text-muted first:mt-0" {...props} />;

// The admin gives an employee a document (a new team member, a change of role): it starts approved,
// and Corax proposes the same access for people in the same situation, as for an approved request.
export default function Grant() {
  const toast = useToast();
  const [people] = useLoad(() => api("GET", "/admin/employees"));
  const [user, setUser] = useState("");
  const [documents, setDocuments] = useState(null);  // null: no employee chosen, or loading
  const [document, setDocument] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  // the documents the chosen employee cannot open yet: the ones they can are not worth giving
  useEffect(() => {
    setDocuments(null);
    setDocument("");
    if (!user) return;
    let current = true;
    api("GET", `/admin/employees/${encodeURIComponent(user)}/documents`).then((answer) => {
      if (!current) return;
      if (answer.status === 200) setDocuments(answer.data.documents);
      else { setDocuments([]); toast(errorText(answer), "no"); }
    });
    return () => { current = false; };
  }, [user, toast]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const answer = await api("POST", "/admin/grants", { user, document, reason: reason.trim() || null });
    setBusy(false);
    if (answer.status !== 201) { toast(errorText(answer), "no"); return; }
    const request = answer.data.request;
    if (request.status === "already_granted") { toast("The employee could read this document already."); return; }
    setFlash(<Notice kind="ok" title="Access given"><p>The employee can read the document now. Decide below whether people in the same situation get it too.</p></Notice>);
    go(`#/admin/request/${request.id}`);
  }

  const head = (
    <PageHead title="Give access">
      Give an employee a document without waiting for them to ask, for example someone who joined a team or changed role. Corax then suggests the same access for people in the same situation.
    </PageHead>
  );
  if (!people || people.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (people.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(people)}</p></Notice></>;

  const placeholder = !user ? "Choose an employee first" : documents === null ? "Loading…"
    : documents.length ? "Choose…" : "This employee can open every document already";
  return (
    <>
      {head}
      <form onSubmit={submit} className="max-w-3xl">
        <Label htmlFor="grantUser">Employee</Label>
        <select id="grantUser" className={inputClass} value={user} onChange={(e) => setUser(e.target.value)} required>
          <option value="">Choose…</option>
          {people.data.employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {titled(e.role)}, {titled(e.department)}</option>)}
        </select>
        <Label htmlFor="grantDocument">Document</Label>
        <select id="grantDocument" className={inputClass} value={document} onChange={(e) => setDocument(e.target.value)}
                required disabled={!documents?.length}>
          <option value="">{placeholder}</option>
          {(documents || []).map((d) => <option key={d.id} value={d.id}>{d.title} · {titled(d.department)}, {d.classification}</option>)}
        </select>
        <p className="mt-1 text-[13px] text-muted">Only the documents this employee cannot open yet are listed.</p>
        <Label htmlFor="grantReason">Why</Label>
        <textarea id="grantReason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                  placeholder="e.g. joined the Finance team" value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className="mt-3 flex justify-end"><Button variant="ok" type="submit" disabled={busy || !document}>Give access</Button></div>
      </form>
    </>
  );
}
