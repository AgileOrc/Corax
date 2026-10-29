import { EMPLOYEE_STATUS, LEVEL, STATUS, titled } from "../format.js";
import { Badge } from "./ui.jsx";

export const LevelBadge = ({ level, className }) => <Badge kind={LEVEL[level] || ""} className={className}>{titled(level)}</Badge>;

// What the employee sees of a request: only whether they can read the document
export function EmployeeBadge({ status }) {
  const [label] = EMPLOYEE_STATUS[status] || [status];
  return <Badge kind={{ Pending: "warn", Approved: "ok" }[label] || "no"} className="py-1!">{label}</Badge>;
}

// What the admin sees of a request
export function StatusBadge({ status }) {
  const [kind, label] = STATUS[status] || ["", status];
  return <Badge kind={kind} dot>{label}</Badge>;
}

const UNIT_STATUS = { pending: ["warn", "Pending"], handled: ["ok", "Answered"], rejected: ["no", "Rejected"] };
export function UnitBadge({ status }) {
  const [kind, label] = UNIT_STATUS[status] || ["", status];
  return <Badge kind={kind} className="py-1!">{label}</Badge>;
}
