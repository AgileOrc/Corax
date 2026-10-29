import { api } from "./api.js";
import { short } from "./format.js";
import { forgetOnSignOut } from "./session.js";

// Names for the admin's pages: employee id -> name, document id -> title. Read once after signing in
// (admins see every employee and document); before that, or for an unknown id, the short id is shown.
let directory = null;
forgetOnSignOut(() => { directory = null; });

export async function loadDirectory() {
  if (directory) return directory;
  const [people, documents] = await Promise.all([api("GET", "/admin/employees"), api("GET", "/documents")]);
  if (people.status !== 200 || documents.status !== 200) return null;
  directory = {
    people: new Map(people.data.employees.map((e) => [e.id, e.name])),
    documents: new Map(documents.data.documents.map((d) => [d.id, d.title])),
  };
  return directory;
}

// "Mia Chen (E012)"; a document's title already carries its id: "Release plan (D004)"
export const personName = (id) => directory?.people.get(id) ? `${directory.people.get(id)} (${short(id)})` : short(id);
export const documentName = (id) => directory?.documents.get(id) || short(id);
