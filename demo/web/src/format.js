// Text helpers of the pages: plain strings only, never HTML (React escapes every string it renders).

export const short = (id) => String(id ?? "").replace(/^[a-z]+_/, "");                  // employee_E037 -> E037
export const words = (s) => String(s ?? "").replace(/_/g, " ");
export const titled = (s) => words(s).replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bHr\b/g, "HR");  // security_officer -> Security Officer
export const project = (p) => titled(String(p ?? "").replace(/(\D)(\d+)$/, "$1 $2"));     // engineering1 -> Engineering 1
export const article = (w) => `${/^[aeiou]/i.test(w) ? "an" : "a"} ${w}`;
export const initials = (name) => String(name ?? "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
// a site and its region: "Paris (EMEA)"
export const place = (site, region) => site ? `${titled(site)} (${String(region || "").toUpperCase()})` : "";

export const ref = (kind, id) => `REQ-${kind === "unit" ? "UNIT" : "DOC"}-${String(id).padStart(4, "0")}`;  // REQ-DOC-0001, REQ-UNIT-0001

export const LEVELS =["public", "internal", "confidential"];
export const LEVEL = { public: "ok", internal: "info", confidential: "no" };

export function ago(iso, now = Date.now()) {
  if (!iso) return "";
  const seconds = (now - Date.parse(iso)) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

// The request statuses of the document app, for employees and for admins.
// What the employee sees: only whether they can read the document, never the rule, its scope or how
// Corax decided (that is for admins).
export const EMPLOYEE_STATUS = {
  pending: ["Pending", "Waiting for an admin."],
  granted: ["Approved", "You can read this document."],
  generalised: ["Approved", "You can read this document."],
  exception_only: ["Approved", "You can read this document."],
  rule_revoked: ["Approved", "You can read this document."],
  already_granted: ["Approved", "You could read this document already."],
  rejected: ["Rejected", "An admin rejected the request."],
  revoked: ["Revoked", "An admin took the access back."],
};

// What the admin sees: [badge kind, label, explanation].
export const STATUS = {
  pending: ["warn", "Pending", "Waiting for an admin."],
  granted: ["ok", "Approved", "Approved for this document. You can still give the same access to people in the same situation."],
  generalised: ["ok", "Approved · also for others", "Approved, and people in the same situation got the same access."],
  exception_only: ["ok", "Approved · this person only", "Approved for this document and this person only."],
  rejected: ["no", "Rejected", "An admin rejected the request."],
  already_granted: ["info", "Already allowed", "The employee could read the document already."],
  rule_revoked: ["warn", "Taken back from others", "The access for people in the same situation was taken back. This person keeps this one document."],
  revoked: ["no", "Revoked", "An admin took the access back."],
};

// A candidate pattern in words, from its predicates (service/patterns.py).
const SHARED = {
  "works_in/owned_by": "the document belongs to their department",
  "based_in/stored_in": "the document is stored in their region",
  "located_in/stored_at": "the document is stored at their site",
  "works_on/belongs_to": "the document is in one of their projects",
  "cleared_for/classified_as": "they are cleared for the document's classification",
  "supports/owned_by": "the document belongs to the department they support",
};
const USER_HAS = {
  holds: (v) => `they are ${article(words(v))}`,
  works_in: (v) => `they work in ${titled(v)}`,
  member_of: (v) => `they are in team ${project(v)}`,
  located_in: (v) => `they work at the ${titled(v)} site`,
  based_in: (v) => `they are based in ${v.toUpperCase()}`,
  works_on: (v) => `they work on ${project(v)}`,
  reports_to: (v) => `they report to ${v}`,
  supports: (v) => `they support ${titled(v)}`,
  cleared_for: (v) => `they are cleared for ${v} documents`,
};

export function inWords(predicates) {
  const parts = (predicates || []).map((p) => {
    const other = short(p.other);
    if (p.kind === "shared") return SHARED[`${p.relation}/${p.other}`] || `their ${words(p.relation)} is the document's ${words(p.other)}`;
    if (p.kind === "user_has") return (USER_HAS[p.relation] || ((v) => `they ${words(p.relation)} ${v}`))(other);
    if (p.kind === "object_has") return `the document ${words(p.relation)} ${words(other)}`;
    return `the document is ${other}`;
  });
  return parts.length ? `Applies when ${parts.join(", and ")}.` : "";
}

// The sentence of a rule the app stored by its technical pattern: Corax's description of that
// candidate, else the app's own wording of its predicates.
export function ruleText(request, pattern) {
  const c = (request.candidates || []).find((x) => x.pattern === pattern);
  return c ? c.description || inWords(c.predicates) : "A rule for people in the same situation.";
}

// The message of a failed API answer ({status, data}).
export function errorText(answer) {
  const d = answer.data || {};
  const detail = typeof d.detail === "string" ? d.detail : d.detail?.message || d.error || d.text;
  return detail ? `${answer.status}: ${detail}` : `The request failed (${answer.status}).`;
}
