import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { LevelBadge, StatusBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Asker, NoteDialog, PeopleList, RevokeButton, ScopeIndicators, TierBadge } from "../../components/admin.jsx";
import { Modal } from "../../components/Modal.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { BackLink, Button, Notice, PageHead } from "../../components/ui.jsx";
import { loadDirectory } from "../../directory.js";
import { takeFlash } from "../../flash.js";
import { ago, errorText, inWords, place, ref, ruleText, STATUS, titled } from "../../format.js";
import { useLoad } from "../../useLoad.js";
import { useApprove, useReject } from "./Requests.jsx";

const HOVER = "hover:text-accent! hover:bg-transparent! hover:border-accent/80!";
const Back = () =><BackLink href="#/admin" label="Back to requests" />;

// One access request: the decision on it, and after approval, Corax's suggestions for people in the
// same situation
export default function Request({ params: [id] }) {
  const [flash, setShown] = useState(null);
  useEffect(() => { setShown(takeFlash()); }, []);
  const [answer, reload] = useLoad(() => api("GET", "/admin/access-requests"));
  // after a decision on this page: its message, then the request as it is now
  const changed = () => { setShown(takeFlash()); reload(); };
  if (!answer || answer.status === 0) return <><Back /><Empty>Loading…</Empty></>;
  const r = answer.status === 200 ? answer.data.requests.find((x) => x.id === Number(id)) : null;
  if (!r) return <><Back /><Empty>{answer.status === 200 ? "No such request." : errorText(answer)}</Empty></>;

  return (
    <>
      <Back />
      {flash && <div className="my-3">{flash}</div>}
      <PageHead title={<span className="flex flex-wrap items-baseline gap-3">{ref("document", r.id)} <span className="text-base font-normal text-muted">sent {ago(r.created_at)}</span></span>}>
        {(r.decided_by || !["pending", "granted"].includes(r.status)) && (
          <span className="flex flex-wrap items-center gap-1.5">
            {!["pending", "granted"].includes(r.status) && <StatusBadge status={r.status} />}
            {r.decided_by && <>decided by <b className="font-semibold text-ink">{r.decided_by}</b> {ago(r.decided_at)}</>}
          </span>
        )}
      </PageHead>
      {/* request */}
      <section className="mb-8 mt-8 space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-lg">
          <b>{r.document_title}</b>
          <span className="text-sm text-muted">| {titled(r.document_department)} - stored at {place(r.document_site, r.document_region)}</span>
          <LevelBadge level={r.document_classification} />
        </div>
        <Asker r={r} label={r.requested_by && r.requested_by !== r.user_id ? `given by ${r.requested_by} to` : "requested by"} />
        {r.reason ? <p className="whitespace-pre-wrap text-sm">“{r.reason}”</p> : <p className="text-[13px] text-muted">No reason given.</p>}
      </section>
      {/* decision */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Decision</h2>
        <Decision r={r} onChange={changed} />
      </section>
    </>
  );
}

function Decision({ r, onChange }) {
  const [rejecting, setRejecting] = useState(false);
  const approve = useApprove(r.id, onChange);
  const reject = useReject(r.id, onChange);
  const [kind, label, explained] = STATUS[r.status] || ["", r.status, ""];

  if (r.status === "pending") {
    return (
      <div className="flex gap-2">
        <Button onClick={approve}>Approve</Button>
        <Button variant="ghost" onClick={() => setRejecting(true)}>Reject</Button>
        {rejecting && <NoteDialog title={`Reject request ${ref("document", r.id)}`} action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
      </div>
    );
  }
  if (r.status === "granted") return <Suggestions r={r} onChange={onChange} />;
  if (r.status === "generalised") {
    return (
      <Notice kind="glass" title={<span className="flex flex-wrap items-center gap-2">Rule applied <TierBadge tier={r.tier} /></span>}>
        <p>{ruleText(r, r.rule_pattern)}</p>
        <p className="mt-1 text-muted">Matching employees now have access. Corax still checks each of their requests.</p>
        <div className="mt-4 flex flex-wrap gap-5">
          <Button size="sm" href="#/rules" className={HOVER}>View access</Button>
          <RevokeButton requestId={r.id} everything={false} label="Revoke rule" variant="ghost" className="font-medium! border-ink/25!" onDone={onChange} />
          <RevokeButton requestId={r.id} everything label="Revoke all" variant="ghost" className="font-medium! border-ink/25!" onDone={onChange} />
        </div>
      </Notice>
    );
  }
  if (["exception_only", "rule_revoked"].includes(r.status) && r.appeal_id) {
    return (
      <Notice kind="glass" title={label}>
        <p>{explained}</p>
        {r.note && <p className="mt-1">Note: {r.note}</p>}
        <div className="mt-4"><RevokeButton requestId={r.id} everything label="Revoke employee access" variant="ghost" className="font-medium! border-ink/25!" onDone={onChange} /></div>
      </Notice>
    );
  }
  return (
    <Notice kind={kind === "no" ? "no" : "glass"} title={label}>
      <p>{explained}</p>
      {r.note && <p className="mt-1">Note: {r.note}</p>}
    </Notice>
  );
}

// The approved request's suggestions for people in the same situation, narrowest first
function Suggestions({ r, onChange }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);  // the answer that needs a second look, or a failure
  const [who, setWho] = useState(null);
  const candidates = r.candidates || [];

  async function confirm(candidate, acknowledge) {
    setBusy(true);
    const answer = await api("POST", `/admin/access-requests/${r.id}/confirm`, { candidate, acknowledge_scope: acknowledge });
    setBusy(false);
    if (answer.status === 200) {
      onChange();
      return;
    }
    if (answer.status === 409 && answer.data?.appeal?.scope) {
      await loadDirectory();
      setResult({ large: answer.data.appeal, candidate });
    } else if (answer.status === 422) {
      setResult({ failed: true });
    } else {
      toast(errorText(answer), "no");
    }
  }

  return (
    <div className="space-y-3">
      {r.note && <Notice kind="accent"><p>{r.note}.</p></Notice>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-muted">Optionally extend this access to people in the same situation.</p>
        <Button variant="ghost" className="font-medium!" disabled={busy} onClick={() => confirm(null, false)}>Only this person</Button>
      </div>
      {candidates.length === 0 ? <p className="text-muted">Corax has no suggestion for people in the same situation.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2">#</th><th className="px-3 py-2">Rule</th>
                <th className="w-px whitespace-nowrap px-5 py-2 text-right" title="People who would gain access">People</th>
                <th className="w-px whitespace-nowrap px-5 py-2 text-right" title="New accesses: one person, one document">Grants</th>
                <th className="w-px whitespace-nowrap px-5 py-2 text-right" title="Mean risk score, from 0 (usual) to 1 (unusual)">Risk</th>
                <th className="w-px whitespace-nowrap px-5 py-2" title="Narrow: few people, applied at once. Broad: needs your confirmation">Reach</th>
                <th className="w-px whitespace-nowrap px-5 py-2 text-right" title="Of the requests most like this one, how many the rule also covers">Match</th><th className="w-px" />
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.index} className="border-b border-line align-top">
                  <td className="px-3 py-5">{c.index}</td>
                  <td className="px-3 py-5">{c.description || inWords(c.predicates)}</td>
                  <td className="w-px whitespace-nowrap px-5 py-5 text-right tabular-nums">{c.scope?.users ?? c.users ?? "?"}</td>
                  <td className="w-px whitespace-nowrap px-5 py-5 text-right tabular-nums">{c.scope ? c.scope.pairs : `${c.estimated ? "~" : ""}${c.pairs}`}</td>
                  <td className="w-px whitespace-nowrap px-5 py-5 text-right tabular-nums">{c.scope?.mean_risk == null ? "–" : Number(c.scope.mean_risk).toFixed(2)}</td>
                  <td className="w-px whitespace-nowrap px-5 py-5"><TierBadge tier={c.scope?.tier} /></td>
                  <td className="w-px whitespace-nowrap px-5 py-5 text-right tabular-nums">{c.similar ? `${c.similar.covered}/${c.similar.of}` : `${Math.round((c.support || 0) * 100)}%`}</td>
                  <td className="w-px py-5 pl-5">
                    <div className="flex gap-3 whitespace-nowrap">
                      <Button variant="ghost" size="sm" className="font-medium!" onClick={() => setWho(c.index)}>Who gains</Button>
                      <Button size="sm" className="hover:text-accent! hover:bg-transparent! hover:border-accent/80!" disabled={busy} onClick={() => confirm(c.index, false)}>Give access</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {result?.failed && (
        <Notice kind="no" title="Corax could not apply this suggestion"><p>A safety check failed, so nothing changed. The employee keeps this one document.</p></Notice>
      )}
      {result?.large && (
        <Notice kind="warn" title="This reaches many people: please confirm">
          <p>Rule #{result.candidate} would give access to many people, or to unusual access, so it needs a second look:</p>
          {result.large.description && <p className="mt-1">{result.large.description}</p>}
          <ScopeIndicators scope={result.large.scope} />
          {result.large.affected && <div className="mt-3"><PeopleList access={result.large.affected} /></div>}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => confirm(result.candidate, true)}>Confirm and give access</Button>
            <Button variant="ghost" disabled={busy} onClick={() => confirm(null, false)}>Only this person</Button>
          </div>
        </Notice>
      )}
      {who && <WhoWouldGain appealId={r.appeal_id} candidate={who} onClose={() => setWho(null)} />}
    </div>
  );
}

// Who a suggestion would give access to, before anything is written
function WhoWouldGain({ appealId, candidate, onClose }) {
  const [answer, setAnswer] = useState(null);
  useEffect(() => {
    let current = true;
    Promise.all([api("GET", `/corax/appeals/${encodeURIComponent(appealId)}/candidates/${candidate}`), loadDirectory()])
      .then(([a]) => { if (current) setAnswer(a); });
    return () => { current = false; };
  }, [appealId, candidate]);

  return (
    <Modal title={`Rule #${candidate}`} onClose={onClose}>
      {!answer ? <p className="text-muted">Asking Corax…</p>
        : answer.status !== 200 ? <Notice kind="warn"><p>{errorText(answer)}</p></Notice>
        : (
          <div className="max-h-[70vh] overflow-y-auto">
            <p>{answer.data.description}</p>
            <ScopeIndicators scope={answer.data.scope} />
            <h3 className="mb-1 mt-4 font-semibold">Who would get access</h3>
            <PeopleList access={answer.data.affected} limit={50} />
          </div>
        )}
    </Modal>
  );
}
