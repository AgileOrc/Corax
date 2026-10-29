// The signed-in user and their JWT, for this tab only (sessionStorage). The page reads the token's
// expiry only to sign out on time: the gateway verifies the signature of every request.
export const session = {
  get token() { return sessionStorage.getItem("token"); },
  get user() { try { return JSON.parse(sessionStorage.getItem("user")); } catch { return null; } },
  save(token, user) { sessionStorage.setItem("token", token); sessionStorage.setItem("user", JSON.stringify(user)); },
  clear() { sessionStorage.removeItem("token"); sessionStorage.removeItem("user"); },
  valid() {
    const token = this.token;
    if (!token || !this.user) return false;
    try {
      const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return payload.exp * 1000 > Date.now() + 5000;
    } catch { return false; }
  },
};

export const home = (user) => user?.kind === "admin" ? "#/admin" : "#/documents";

// What the pages keep between visits (filters, lists read once), dropped on sign-out: not the next user's
const resets = [];
export const forgetOnSignOut = (reset) => { resets.push(reset); };
export const forgetAll = () => resets.forEach((reset) => reset());
