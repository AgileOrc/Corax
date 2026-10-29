import { useState } from "react";

import { api } from "../api.js";
import { UnitBadge } from "../components/badges.jsx";
import { Empty } from "../components/DocRow.jsx";
import { useToast } from "../components/Toasts.jsx";
import { Button, inputClass, Notice, PageHead } from "../components/ui.jsx";
import { ago, errorText, titled } from "../format.js";
import { useLoad } from "../useLoad.js";

// The employee asks for documents of a unit without knowing which: they choose the unit from a list
// (never typed, never a title) and say why. The admin decides which documents, if any.
export default function Units() {
  const toast = useToast();
  const [page, reload] = useLoad(async () => {
    const [units, requests] = await Promise.all([api("GET", "/units"), api("GET", "/unit-requests")]);
    return { units, requests };
  });
  const [unit, setUnit] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const head = (
    <PageHead title="Ask for a unit">
      Need documents of another unit but do not know which? Choose the unit and say what you need. An admin decides what to share with you.
    </PageHead>
  );
  if (!page || page.units.status === 0) return <>{head}<div><Empty>Loading…</Empty></div></>;
  if (page.units.status !== 200) return <>{head}<div><Notice kind="warn"><p>{errorText(page.units)}</p></Notice></div></>;

  const units = page.units.data.units;
  const chosen = unit || units[0] || "";
  const mine = page.requests.data?.requests || [];

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const answer = await api("POST", "/unit-requests", { unit: chosen, reason: reason.trim() || null });
    setBusy(false);
    if (answer.status === 201) { toast("Sent: an admin will decide."); setReason(""); reload(); } else toast(errorText(answer), "no");
  }

  return (
    <>
      {head}
      <div>
        <form onSubmit={submit}>
          <label htmlFor="unit" className="mb-1 block text-[13px] font-medium text-muted">Unit</label>
          <select id="unit" className={inputClass} value={chosen} onChange={(e) => setUnit(e.target.value)} required>
            {units.map((u) => <option key={u} value={u}>{titled(u)}</option>)}
          </select>
          <label htmlFor="unitReason" className="mb-1 mt-3 block text-[13px] font-medium text-muted">What do you need it for?</label>
          <textarea id="unitReason" className={`${inputClass} min-h-[84px] resize-y`} maxLength={1000}
                    placeholder="e.g. the grant budget of my program" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="mt-3 flex justify-end"><Button type="submit" disabled={busy}>Send</Button></div>
        </form>
      </div>
      <div className="mt-10">
        <h2 className="text-lg font-semibold">Your unit requests</h2>
        {mine.length === 0 ? <Empty>None yet.</Empty> : mine.map((r) => (
          <article key={r.id} className="border-b border-line px-1 py-4 last:border-b-0">
            <h3 className="flex flex-wrap items-center gap-2 font-semibold">{titled(r.unit)} <UnitBadge status={r.status} /></h3>
            <p className="mt-1 text-[13px] text-muted">#{r.id} · sent {ago(r.created_at)}{r.decided_at ? ` · answered ${ago(r.decided_at)}` : ""}</p>
            {r.status === "handled" && <p className="mt-1.5 text-sm">{r.given} document{r.given === 1 ? "" : "s"} shared with you. <a href="#/shared">Shared with me</a></p>}
            {r.note && <p className="mt-1 text-[13px] text-muted">Note: {r.note}</p>}
          </article>
        ))}
      </div>
    </>
  );
}
