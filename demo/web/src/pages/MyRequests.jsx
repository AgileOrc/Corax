import { api } from "../api.js";
import { EmployeeBadge, LevelBadge } from "../components/badges.jsx";
import { Empty } from "../components/DocRow.jsx";
import { Button, Notice, PageHead } from "../components/ui.jsx";
import { ago, EMPLOYEE_STATUS, errorText, short } from "../format.js";
import { useLoad } from "../useLoad.js";

const OPENS = ["granted", "generalised", "exception_only", "already_granted"];

// The documents the employee asked for, and what the admin decided: never how Corax decided
export default function MyRequests() {
  const [answer, reload] = useLoad(() => api("GET", "/access-requests"));
  const head = (
    <PageHead title="My requests" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Documents you asked for, and what the admin decided.
    </PageHead>
  );
  if (!answer || answer.status === 0) return <>{head}<div><Empty>Loading…</Empty></div></>;
  if (answer.status !== 200) return <>{head}<div><Notice kind="warn"><p>{errorText(answer)}</p></Notice></div></>;

  const requests = answer.data.requests;
  return (
    <>
      {head}
      <div>
        {requests.length === 0 ? <Empty>No requests yet. When Corax denies a document, ask for access from its page.</Empty> : requests.map((r) => (
          <article key={r.id} className="grid grid-cols-1 gap-3.5 border-b border-line px-1 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto]">
            <div>
              <h3 className="flex flex-wrap items-center gap-2 font-semibold">
                <a href={`#/documents/${r.document_id}`} className="text-ink">{r.document_title || `Document ${short(r.document_id)}`}</a>
                <EmployeeBadge status={r.status} />
              </h3>
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
                #{r.id} · {short(r.document_id)}
                {r.document_classification && <> · <LevelBadge level={r.document_classification} /></>}
                {" "}· sent {ago(r.created_at)}{r.decided_at ? ` · decided ${ago(r.decided_at)}` : ""}
              </p>
              {r.reason && <p className="mt-1.5 text-sm">“{r.reason}”</p>}
              <p className="mt-1.5 text-sm text-muted">{(EMPLOYEE_STATUS[r.status] || [])[1] || ""}</p>
              {r.note && <p className="mt-1 text-[13px] text-muted">Note: {r.note}</p>}
            </div>
            {OPENS.includes(r.status) && <div><Button size="sm" href={`#/documents/${r.document_id}`}>Open document</Button></div>}
          </article>
        ))}
      </div>
    </>
  );
}
