import { place, project, titled } from "../format.js";
import { LevelBadge } from "./badges.jsx";
import { Badge } from "./ui.jsx";

// One document in a list: its title (a link) with its tags, its details, and the actions on the right
export function DocRow({ doc, tags, actions, link = true, onOpen }) {
  return (
    <li className="grid grid-cols-1 items-center gap-3 border-b border-line px-1 py-3.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {onOpen ? <button type="button" onClick={onOpen} className="cursor-pointer text-left font-semibold text-ink underline-offset-4 hover:underline">{doc.title}</button>
            : link ? <a href={`#/documents/${doc.id}`} className="font-semibold text-ink">{doc.title}</a>
            : <span className="font-semibold">{doc.title}</span>}
          {doc.classification && <LevelBadge level={doc.classification} />}
          {tags?.map((tag) => <Badge key={tag} kind="accent">{tag}</Badge>)}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          {doc.department && <span>{titled(doc.department)}{doc.projects?.length ? ` (${doc.projects.map(project).join(", ")})   -  ` : ""}</span>}
          {doc.site && <span>Stored at {place(doc.site, doc.region)}</span>}
        </div>
      </div>
      {actions && <div className="flex gap-3">{actions}</div>}
    </li>
  );
}

export const Empty = ({ children }) => <p className="py-8 text-center text-muted">{children}</p>;
