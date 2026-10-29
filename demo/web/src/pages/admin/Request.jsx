import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { LevelBadge, StatusBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { NoteDialog, PeopleList, Person, RevokeButton, ScopeIndicators, TierBadge } from "../../components/admin.jsx";
import { Modal } from "../../components/Modal.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, Notice, PageHead } from "../../components/ui.jsx";
import { loadDirectory } from "../../directory.js";
import { setFlash, takeFlash } from "../../flash.js";
import { ago, errorText, inWords, place, ruleText, STATUS, titled } from "../../format.js";
import { useLoad } from "../../useLoad.js";
import { useApprove, useReject } from "./Requests.jsx";

const Back = () => <a href="#/admin" className="text-[13px]">← Access requests</a>;

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
      <PageHead title={`Request #${r.id}`}>
        <span className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={r.status} /> sent {ago(r.created_at)}{r.decided_by ? `, decided by ${r.decided_by} ${ago(r.decided_at)}` : ""}
        </span>
      </PageHead>
      <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Decision</h2>
          <Decision r={r} onChange={changed} />
        </section>
        <section className="space-y-3">
          <Person r={r} />
          <div>
            <span className="text-[13px] text-muted">asks for</span>
            <div><b>{r.document_title}</b> <span className="font-mono text-[13px] text-muted">{r.document_id}</span></div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
              <LevelBadge level={r.document_classification} />
              <span>{titled(r.document_department)}</span>
              <span>Stored at {place(r.document_site, r.document_region)}</span>
            </div>
          </div>
          {r.reason ? <p className="text-sm">“{r.reason}”</p> : <p className="text-[13px] text-muted">No reason given.</p>}
        </section>
      </div>
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
        <Button variant="ok" onClick={approve}>Approve</Button>
        <Button variant="ghost" onClick={() => setRejecting(true)}>Reject</Button>
        {rejecting && <NoteDialog title={`Reject request #${r.id}`} action="Reject" onClose={() => setRejecting(false)} onSubmit={reject} />}
      </div>
    );
  }
  if (r.status === "granted") return <Suggestions r={r} onChange={onChange} />;
  if (r.status === "generalised") {
    return (
      <Notice kind="ok" title={<span className="flex flex-wrap items-center gap-2">Access given to people in the same situation <TierBadge tier={r.tier} /></span>}>
        <p>{ruleText(r, r.rule_pattern)}</p>
        <p className="mt-1">People in the same situation can read these documents now. Unusual requests from them can still be blocked.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" href="#/rules">Who gained access</Button>
          <RevokeButton requestId={r.id} everything={false} label="Take back from others" onDone={onChange} />
          <RevokeButton requestId={r.id} everything label="Take back from everyone" variant="ghost" onDone={onChange} />
        </div>
      </Notice>
    );
  }
  if (["exception_only", "rule_revoked"].includes(r.status) && r.appeal_id) {
    return (
      <Notice kind="info" title={label}>
        <p>{explained}</p>
        {r.note && <p className="mt-1">Note: {r.note}</p>}
        <div className="mt-3"><RevokeButton requestId={r.id} everything label="Revoke the employee's access too" onDone={onChange} /></div>
      </Notice>
    );
  }
  return (
    <Notice kind={kind === "no" ? "no" : "info"} title={label}>
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
      const appeal = answer.data.appeal;
      setFlash(appeal.status === "rule_applied" ? <RuleNotice appeal={appeal} />
        : <Notice kind="ok" title="Only the exception was kept"><p>The employee has this one document; no rule for others.</p></Notice>);
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
      {r.note && <Notice kind="info"><p>{r.note}.</p></Notice>}
      <p className="text-muted">The employee can read the document now. To give the same access to people in the same situation, choose one of Corax's suggestions below, narrowest first.</p>
      {candidates.length === 0 ? <p className="text-muted">Corax has no suggestion for people in the same situation.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-1.5 py-2">#</th><th className="px-1.5 py-2">Suggestion</th>
                <th className="px-1.5 py-2 text-right">People</th><th className="px-1.5 py-2 text-right">New accesses</th>
                <th className="px-1.5 py-2 text-right">How unusual (0–1)</th><th className="px-1.5 py-2">Reach</th>
                <th className="px-1.5 py-2 text-right">Like this request</th><th />
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.index} className="border-b border-line align-top">
                  <td className="px-1.5 py-2.5">{c.index}</td>
                  <td className="px-1.5 py-2.5">
                    <div>{c.description || inWords(c.predicates)}</div>
                    <Button variant="ghost" size="sm" className="mt-1.5" onClick={() => setWho(c.index)}>Who would gain access</Button>
                  </td>
                  <td className="px-1.5 py-2.5 text-right tabular-nums">{c.scope?.users ?? c.users ?? "?"}</td>
                  <td className="px-1.5 py-2.5 text-right tabular-nums">{c.scope ? c.scope.pairs : `${c.estimated ? "~" : ""}${c.pairs}`}</td>
                  <td className="px-1.5 py-2.5 text-right tabular-nums">{c.scope?.mean_risk == null ? "–" : Number(c.scope.mean_risk).toFixed(2)}</td>
                  <td className="px-1.5 py-2.5"><TierBadge tier={c.scope?.tier} /></td>
                  <td className="whitespace-nowrap px-1.5 py-2.5 text-right tabular-nums">{c.similar ? `${c.similar.covered} of ${c.similar.of}` : `${Math.round((c.support || 0) * 100)}%`}</td>
                  <td className="px-1.5 py-2.5"><Button size="sm" disabled={busy} onClick={() => confirm(c.index, false)}>Give access</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[13px] text-muted">Like this request: of the requests most like this one, how many the suggestion would also cover.</p>
        </div>
      )}
      <div className="flex justify-end"><Button variant="ghost" disabled={busy} onClick={() => confirm(null, false)}>Only this person</Button></div>
      {result?.failed && (
        <Notice kind="no" title="Corax could not apply this suggestion"><p>A safety check failed, so nothing changed. The employee keeps this one document.</p></Notice>
      )}
      {result?.large && (
        <Notice kind="warn" title="This reaches many people: please confirm">
          <p>Suggestion #{result.candidate} would give access to many people, or to unusual access, so it needs a second look:</p>
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

// The notice after the admin gave a suggestion to people in the same situation
function RuleNotice({ appeal }) {
  const scope = appeal.chosen.scope;
  return (
    <Notice kind="ok" title={<span className="flex flex-wrap items-center gap-2">Access given to people in the same situation <TierBadge tier={scope.tier} /></span>}>
      <p>{scope.tier === "small" ? "Done right away, because it reaches only a few people." : "Done after you confirmed it."} It works right away.</p>
      {appeal.chosen.description && <p className="mt-1">{appeal.chosen.description}</p>}
      <ScopeIndicators scope={scope} />
      <p className="mt-3"><a href="#/rules">See who gained access and how it is used</a></p>
      <p className="mt-1 text-[13px] text-muted">Checked automatically before it took effect.</p>
    </Notice>
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
    <Modal title={`Suggestion #${candidate}`} onClose={onClose}>
      {!answer ? <p className="text-muted">Asking Corax…</p>
        : answer.status !== 200 ? <Notice kind="warn"><p>{errorText(answer)}</p></Notice>
        : (
          <div className="max-h-[70vh] overflow-y-auto">
            <p>{answer.data.description}</p>
            <ScopeIndicators scope={answer.data.scope} />
            <h3 className="mb-1 mt-4 font-semibold">Who would get access</h3>
            <PeopleList access={answer.data.affected} limit={50} />
            <p className="mt-3 text-[13px] text-muted">Nothing is written until you apply it.</p>
          </div>
        )}
    </Modal>
  );
}
