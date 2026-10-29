import { api } from "../../api.js";
import { UnitBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Row } from "../../components/admin.jsx";
import { Button, Notice, PageHead } from "../../components/ui.jsx";
import { errorText, titled } from "../../format.js";
import { useLoad } from "../../useLoad.js";

// Employees who need documents of a unit but do not know which ones
export default function UnitRequests() {
  const [answer, reload] = useLoad(() => api("GET", "/admin/unit-requests"));
  const head = (
    <PageHead title="Unit requests" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Employees who need documents of a unit but do not know which ones.
    </PageHead>
  );
  if (!answer || answer.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (answer.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(answer)}</p></Notice></>;

  const requests = answer.data.requests;
  return (
    <>
      {head}
      {requests.length === 0 ? <Empty>No unit requests.</Empty> : requests.map((r) => (
        <Row key={r.id} actions={r.status === "pending" ? <Button size="sm" href={`#/unit-requests/${r.id}`}>Decide</Button> : null}>
          <div><b>{r.user_name}</b> <span className="text-[13px] text-muted">{titled(r.user_role)}, {titled(r.user_department)}</span></div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] text-muted">asks for documents of</span> <b>{titled(r.unit)}</b> <UnitBadge status={r.status} />
          </div>
          {r.reason && <p className="text-sm">“{r.reason}”</p>}
        </Row>
      ))}
    </>
  );
}
