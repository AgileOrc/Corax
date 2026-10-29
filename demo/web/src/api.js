import { session } from "./session.js";

// What the page does when a call cannot be made: set once by App (sign out, show a message).
let trouble = { expired: () => {}, unreachable: () => {} };
export const onApiTrouble = (handlers) => { trouble = handlers; };

// fetch through the gateway. Returns {status, data}; status 0 when the session ended or the gateway
// is unreachable (then the page has already moved on). A request Corax denies comes back as 403.
export async function api(method, path, body) {
  const login = path === "/auth/login";
  if (!login && !session.valid()) { trouble.expired(); return { status: 0, data: null }; }
  const headers = {};
  if (!login) headers.Authorization = `Bearer ${session.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    trouble.unreachable();
    return { status: 0, data: null };
  }
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { text }; }
  return { status: response.status, data };
}
