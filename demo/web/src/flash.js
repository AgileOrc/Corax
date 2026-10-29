// A message for the next page, shown once: "Approved" above the request the admin is sent to.
let next = null;
export const setFlash = (message) => { next = message; };
export function takeFlash() {
  const message = next;
  next = null;
  return message;
}
