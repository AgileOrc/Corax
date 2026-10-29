import { api } from "../../api.js";
import { Empty } from "../../components/DocRow.jsx";
import { PeopleList, RevokeButton, Row } from "../../components/admin.jsx";
import { Badge, Button, Notice, PageHead } from "../../components/ui.jsx";
import { documentName, loadDirectory, personName } from "../../directory.js";
import { errorText } from "../../format.js";
import { useLoad } from "../../useLoad.js";

// Every rule and exception from an approved request still in effect: who approved it, who gained
// access, and every time that access was used since (GET /corax/rules).
export default function Rules() {
  const [page, reload] = useLoad(async () => {
    const [rules, requests] = await Promise.all([api("GET", "/corax/rules"), api("GET", "/admin/access-requests"), loadDirectory()]);
    return { rules, requests };
  });
  const head = (
    <PageHead title="Access granted" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Every rule and exception an admin approved that is still in effect: who gained access, and every time that access was used since. Revoking deletes the rule and records who did it.
    </PageHead>
  );
  if (!page || page.rules.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (page.rules.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(page.rules)}</p></Notice></>;

  const requestOf = new Map((page.requests.data?.requests || []).filter((r) => r.appeal_id).map((r) => [r.appeal_id, r]));
  const rules = page.rules.data;
  return (
    <>
      {head}
      {rules.length === 0 ? <Empty>No access granted through requests yet.</Empty> : rules.map((e) => {
        const r = requestOf.get(e.appeal);
        const used = e.summary.find((line) => line.startsWith("Used") || line.startsWith("Not used"));
        return (
          <Row key={`${e.appeal}/${e.kind}`}
               actions={r ? <RevokeButton requestId={r.id} everything={e.kind !== "rule"} label="Revoke" onDone={reload} /> : null}>
            <h3 className="flex flex-wrap items-center gap-2 font-semibold">
              {e.description} <Badge kind={e.kind === "rule" ? "accent" : ""}>{e.kind === "rule" ? "for a group" : "one person"}</Badge>
            </h3>
            <p className="text-[13px] text-muted">
              {e.summary[1]}{r && <> · request <a href={`#/admin/request/${r.id}`}>#{r.id}</a></>} · {e.appeal}
            </p>
            {e.file_missing && <Notice kind="warn"><p>This access was removed outside Corax, so nobody recorded who did it.</p></Notice>}
            <div>
              <h4 className="font-semibold">Gained access</h4>
              <PeopleList access={e.access} />
            </div>
            <div>
              <h4 className="font-semibold">{used}</h4>
              {e.uses?.length > 0 && (
                <ul className="list-disc pl-5 text-[13px]">
                  {e.uses.map((u, i) => (
                    <li key={i}>{new Date(u.at).toLocaleString()}: <b>{personName(u.user)}</b> opened {documentName(u.object)}</li>
                  ))}
                </ul>
              )}
            </div>
          </Row>
        );
      })}
    </>
  );
}
