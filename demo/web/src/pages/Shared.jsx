import { useEffect } from "react";

import { api } from "../api.js";
import { DocRow, Empty } from "../components/DocRow.jsx";
import { Button, Notice, PageHead } from "../components/ui.jsx";
import { markShared, sharedWithMe } from "../shared.js";
import { useLoad } from "../useLoad.js";

// What the employee can read through approved requests, their own or a rule for their situation
export default function Shared() {
  const [page, reload] = useLoad(async () => {
    const [shared, catalog] = await Promise.all([sharedWithMe(), api("GET", "/documents")]);
    return { shared, catalog };
  });
  // seen once listed: the next visit marks only newer ones as new
  useEffect(() => { if (page?.shared) markShared(page.shared.ids); }, [page]);

  const head = (
    <PageHead title="Shared with me" actions={<Button variant="ghost" onClick={reload}>Refresh</Button>}>
      Documents you can read because an admin approved access: your own requests, and rules for people in your situation that you never had to ask for.
    </PageHead>
  );
  if (!page) return <>{head}<div><Empty>Loading…</Empty></div></>;
  if (!page.shared) return <>{head}<div><Notice kind="warn"><p>Corax did not answer. Try again later.</p></Notice></div></>;

  const byId = new Map((page.catalog.data?.documents || []).map((d) => [d.id, d]));
  const fresh = new Set(page.shared.fresh);
  return (
    <>
      {head}
      <div>
        {page.shared.ids.length === 0 ? <Empty>Nothing shared with you yet.</Empty> : (
          <ul>
            {page.shared.ids.map((id) => (
              <DocRow key={id} doc={byId.get(id) || { id, title: id }} tags={fresh.has(id) ? ["New"] : []}
                      actions={<Button size="sm" href={`#/documents/${id}`}>Open</Button>} />
            ))}
          </ul>
        )}
        <p className="mt-2 text-[13px] text-muted">Documents your own projects and role already give you are not listed here.</p>
      </div>
    </>
  );
}
