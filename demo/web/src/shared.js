import { api } from "./api.js";
import { session } from "./session.js";

// The documents this employee can read because an admin approved an access request: their own, and
// those of a rule for people in the same situation, which they never asked for. Corax answers it from
// the token alone (GET /corax/me/access). Which ones are new is remembered in this browser only.
const seenKey = () => `corax.shared.${session.user?.id}`;

function seenShared() {
  try { return new Set(JSON.parse(localStorage.getItem(seenKey()) || "[]")); } catch { return new Set(); }
}

export function markShared(ids) {
  try { localStorage.setItem(seenKey(), JSON.stringify(ids)); } catch { /* no storage: everything stays new */ }
}

// {ids, fresh} or null when Corax did not answer
export async function sharedWithMe() {
  const answer = await api("GET", "/corax/me/access");
  if (answer.status !== 200) return null;
  const ids = answer.data.resources || [];
  const seen = seenShared();
  return { ids, fresh: ids.filter((id) => !seen.has(id)) };
}
