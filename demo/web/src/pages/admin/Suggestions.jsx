import { useState } from "react";

import { api } from "../../api.js";
import { LevelBadge } from "../../components/badges.jsx";
import { Empty } from "../../components/DocRow.jsx";
import { Row } from "../../components/admin.jsx";
import { useToast } from "../../components/Toasts.jsx";
import { Button, Notice, PageHead } from "../../components/ui.jsx";
import { setFlash } from "../../flash.js";
import { errorText, titled } from "../../format.js";
import { go } from "../../router.js";
import { useLoad } from "../../useLoad.js";

// Access Corax's model expects but nobody granted yet: most of the people most like this employee can
// open the document, and the request would look normal. Only admins see this list.
export default function Suggestions() {
  const toast = useToast();
  const [answer, reload] = useLoad(() => api("GET", "/admin/suggestions"));
  const [busy, setBusy] = useState(null);

  async function give(s) {
    setBusy(`${s.user}/${s.object}`);
    const given = await api("POST", "/admin/grants", { user: s.user, document: s.object, reason: "suggested by Corax" });
    setBusy(null);
    if (given.status !== 201) { toast(errorText(given), "no"); return; }
    setFlash(<Notice kind="ok" title="Access given"><p>Decide below whether people in the same situation get it too.</p></Notice>);
    go(`#/admin/request/${given.data.request.id}`);
  }

  async function dismiss(s) {
    setBusy(`${s.user}/${s.object}`);
    const done = await api("POST", "/admin/suggestions/dismiss", { user: s.user, document: s.object });
    setBusy(null);
    if (done.status === 200) { toast("Dismissed."); reload(); } else toast(errorText(done), "no");
  }

  const head = (
    <PageHead title="Suggested access" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Access Corax expects but nobody has given yet: most of the people most like this employee can open the document. The employee does not see this list. Nothing is given until you choose.
    </PageHead>
  );
  if (!answer || answer.status === 0) return <>{head}<Empty>Loading…</Empty></>;
  if (answer.status !== 200) return <>{head}<Notice kind="warn"><p>{errorText(answer)}</p></Notice></>;

  const suggestions = answer.data.suggestions;
  return (
    <>
      {head}
      {suggestions.length === 0 ? <Empty>No suggestions right now.</Empty> : suggestions.map((s) => {
        const working = busy === `${s.user}/${s.object}`;
        return (
          <Row key={`${s.user}/${s.object}`} actions={<>
            <Button variant="ok" size="sm" disabled={working} onClick={() => give(s)}>Give access</Button>
            <Button variant="ghost" size="sm" disabled={working} onClick={() => dismiss(s)}>Dismiss</Button>
          </>}>
            <div><b>{s.user_name}</b> <span className="text-[13px] text-muted">{titled(s.user_role)}, {titled(s.user_department)}</span></div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[13px] text-muted">may need</span> <b>{s.document_title}</b>
              <LevelBadge level={s.document_classification} />
              <span className="text-[13px] text-muted">{titled(s.document_department)}</span>
            </div>
            <p className="text-[13px]">{s.peers.with_access} of the {s.peers.of} people most like them can open it.</p>
          </Row>
        );
      })}
    </>
  );
}
