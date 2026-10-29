import { useState } from "react";

import { api } from "../../api.js";
import { inputClass, PageHead } from "../../components/ui.jsx";
import { ref } from "../../format.js";
import { useSession } from "../../SessionContext.jsx";
import { useLoad } from "../../useLoad.js";

// audit log page
export default function Audit() {
  const { user } = useSession();
  const [page] = useLoad(async () => {
    const requests = await api("GET", "/admin/access-requests");
    const list = requests.data?.requests || [];
    const ids = [...new Set(list.map((r) => r.appeal_id).filter(Boolean))];
    const appeals = await Promise.all(ids.map((id) => api("GET", `/corax/appeals/${encodeURIComponent(id)}`)));
    return { requests: list, appeals };
  });
  const [q, setQ] = useState("");
  const [event, setEvent] = useState("");
  const [actor, setActor] = useState("");
  const [open, setOpen] = useState(null);

  const requests = page?.requests || [];
  const requestOf = new Map(requests.filter((r) => r.appeal_id).map((r) => [r.appeal_id, r]));
  const records = (page?.appeals || []).filter((a) => a.status === 200).map((a) => a.data);
  const events = [
    ...records.flatMap((record) => record.history.map((h, i) => ({ key: `${record.id}/${i}`, ...h, record, request: requestOf.get(record.id) }))),
    ...requests.filter((r) => r.status === "rejected" && r.decided_at).map((r) => ({ key: `request/${r.id}`, at: r.decided_at, event: "request_rejected", by: r.decided_by, request: r })),
  ].sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const kinds = [...new Set(events.map((e) => e.event))].sort();
  const actors = [...new Set(events.map((e) => e.by).filter(Boolean))].sort();
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = events.filter((e) => (!event || e.event === event) && (!actor || e.by === actor)
    && words.every((w) => JSON.stringify([e.at, e.by, e.event, e.record, e.request]).toLowerCase().includes(w)));
  const command = ["tail audit.log", ...words.map((w) => `grep -i "${w}"`), event && `grep "${event}"`, actor && `grep "${actor}"`].filter(Boolean).join(" | ");

  return (
    <>
      <PageHead title="Audit log">Every admin action on access, as Corax recorded it. Risk scores are in the service log.</PageHead>
      {/* search and filters */}
      <form role="search" onSubmit={(e) => e.preventDefault()}
            className="mb-4 grid grid-cols-1 items-end gap-2.5 sm:grid-cols-2 lg:w-3/4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="sm:col-span-2 lg:col-span-1">
          <Label htmlFor="auditQ">Search</Label>
          <input id="auditQ" className={inputClass} autoComplete="off" spellCheck="false" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Any id or value, e.g. employee_E040 appeal-0002 large" />
        </div>
        <div>
          <Label htmlFor="auditEvent">Event</Label>
          <select id="auditEvent" className={inputClass} value={event} onChange={(e) => setEvent(e.target.value)}>
            <option value="">All</option>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
        <div>
          <Label htmlFor="auditActor">Actor</Label>
          <select id="auditActor" className={inputClass} value={actor} onChange={(e) => setActor(e.target.value)}>
            <option value="">All</option>
            {actors.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </form>
      {/* terminal */}
      <div className="overflow-hidden rounded-xl border border-white/10 bg-[#0c0c0b] font-mono text-[12.5px] leading-relaxed text-zinc-300 shadow-card">
        <div className="flex items-center gap-2 border-b border-white/10 bg-white/5 px-4 py-2.5">
          <span className="size-3 rounded-full bg-[#ff5f57]" />
          <span className="size-3 rounded-full bg-[#febc2e]" />
          <span className="size-3 rounded-full bg-[#28c840]" />
          <span className="ml-3 text-xs text-zinc-500">{user.id}@corax: ~/appeals — audit.log</span>
        </div>
        <div className="overflow-x-auto whitespace-nowrap border-b border-white/10 px-4 py-2.5">
          <span className="text-emerald-400">{user.id}@corax</span><span className="text-zinc-500">:~$ </span>
          <span className="text-zinc-200">{command}</span>
        </div>
        <div className="max-h-[70vh] overflow-auto px-4 py-3">
          {!page ? <p className="text-zinc-500">reading appeals…</p>
            : events.length === 0 ? <p className="text-zinc-500"># no admin action yet</p>
            : (
              <>
                <p className="mb-2 text-zinc-600"># {shown.length} of {events.length} events, newest first · click a line for its raw record</p>
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wider text-zinc-500">
                      <th className="w-px whitespace-nowrap py-1.5 pr-6 font-normal">Timestamp</th>
                      <th className="py-1.5 font-normal">Activity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((e) => (
                      <tr key={e.key} onClick={() => setOpen(open === e.key ? null : e.key)}
                          className="cursor-pointer border-b border-white/5 align-top hover:bg-white/5">
                        <td className="whitespace-nowrap py-2 pr-6 text-zinc-500">{e.at}</td>
                        <td className="py-2">
                          <Line e={e} />
                          {open === e.key && (
                            <pre className="mt-2 overflow-x-auto rounded border border-white/10 bg-black/40 px-3 py-2 text-[12px] text-zinc-400">{JSON.stringify(e.record || e.request, null, 2)}</pre>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          <p className="mt-2 text-zinc-500">{user.id}@corax:~$ <span className="animate-pulse text-[#d4b062]">▋</span></p>
        </div>
      </div>
    </>
  );
}

const COLOR = { applied: "text-emerald-400", revoked: "text-rose-400", rejected: "text-rose-400" };
const color = (event) => Object.entries(COLOR).find(([k]) => event.includes(k))?.[1] || "text-amber-300";
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const cmp = (value, limit) => (value > limit ? ">" : "≤");

// audit line
function Line({ e }) {
  const a = e.record?.appeal;
  const chosen = e.record?.chosen;
  const s = chosen?.scope;
  const l = chosen?.limits;
  const head = (
    <div className="whitespace-nowrap">
      <span className="text-sky-300">{e.by || "-"}</span>{"  "}
      <span className={color(e.event)}>{e.event.padEnd(18)}</span>{" "}
      {e.record && <span className="text-zinc-100">{e.record.id}</span>}
      {e.request && <span className="text-zinc-500">  request={ref("document", e.request.id)}</span>}
    </div>
  );
  if (e.event === "request_rejected") {
    return <>{head}<Kv pairs={[["subject", e.request.user_id], ["object", e.request.document_id], ["note", e.request.note ? JSON.stringify(e.request.note) : null]]} /></>;
  }
  if (["rule_applied", "rule_rejected"].includes(e.event) && chosen) {
    return (
      <>
        {head}
        <Kv pairs={[["candidate", `#${chosen.candidate}`], ["pattern", chosen.pattern]]} />
        {s && (
          <Kv pairs={[
            ["users", `${s.users} (${pct(s.user_share)})${l ? ` ${cmp(s.user_share, l.max_user_share)} max_user_share=${pct(l.max_user_share)}` : ""}`],
            ["pairs", `${s.pairs}${l ? ` ${cmp(s.pairs, l.max_pairs)} max_pairs=${l.max_pairs}` : ""}`],
            ["mean_risk", `${s.mean_risk == null ? "null" : s.mean_risk.toFixed(4)}${l && s.mean_risk != null ? ` ${cmp(s.mean_risk, l.max_mean_risk)} max_mean_risk=${l.max_mean_risk}` : ""}`],
            ["tier", s.tier],
          ]} />
        )}
        {e.event === "rule_applied" && e.record.files?.rule && <Kv pairs={[["file", e.record.files.rule]]} />}
      </>
    );
  }
  if (a && ["created", "exception_applied"].includes(e.event)) {
    return (
      <>
        {head}
        <Kv pairs={[["subject", a.user], ["object", a.object], ["action", a.action], ["reason", a.reason ? JSON.stringify(a.reason) : null]]} />
        {e.event === "exception_applied" && e.record.files?.exception && <Kv pairs={[["file", e.record.files.exception]]} />}
      </>
    );
  }
  return <>{head}{a && <Kv pairs={[["subject", a.user], ["object", a.object]]} />}</>;
}

const Kv = ({ pairs }) => (
  <div className="whitespace-nowrap pl-6">
    {pairs.filter(([, v]) => v != null && v !== "").map(([k, v], i) => (
      <span key={k}>{i > 0 && "   "}<span className="text-zinc-500">{k}=</span><span className="text-zinc-200">{v}</span></span>
    ))}
  </div>
);

const Label = (props) => <label className="mb-1 block text-[13px] font-medium text-muted" {...props} />;
