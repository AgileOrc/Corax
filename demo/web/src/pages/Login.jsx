import { useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { errorText } from "../format.js";
import { useSession } from "../SessionContext.jsx";

// The demo accounts: those of the prepared data (assets/accounts.json, written by scripts/demo_office.py
// prepare), or these, of the enterprise of scripts/prepare/make_enterprise.py.
const ACCOUNTS = [
  ["e049", "Engineering coordinator"], ["e085", "Finance coordinator"], ["e040", "Engineer"],
  ["e003", "Sales analyst"], ["e001", "Sales manager"], ["e076", "Auditor"], ["admin_01", "Corax admin"],
];

// an input drawn as a line, on the see-through card
const LINE_INPUT = "w-full border-0 border-b border-glass-line bg-transparent px-1 py-2 text-lg text-ink placeholder:text-ink/80 focus:border-ink focus:outline-none";

// How many of the employee accounts the page leaves out of its buttons (the last ones), so the list
// stays short. The admin's is always shown, and every account still signs in by typing its username.
const HIDDEN = 5;

async function demoAccounts() {
  let all = ACCOUNTS;
  try {
    const response = await fetch("/assets/accounts.json");
    const accounts = response.ok ? (await response.json()).accounts : null;
    if (Array.isArray(accounts) && accounts.length) all = accounts.map((a) => [a.username, a.label]);
  } catch { /* no prepared accounts: the built-in ones */ }
  const admins = all.filter(([user]) => user.startsWith("admin"));
  const employees = all.filter(([user]) => !user.startsWith("admin"));
  return [...employees.slice(0, Math.max(employees.length - HIDDEN, 1)), ...admins];
}

export default function Login() {
  const { signIn } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const passwordInput = useRef(null);

  useEffect(() => {
    let current = true;
    demoAccounts().then((found) => { if (current) setAccounts(found); });
    return () => { current = false; };
  }, []);

  async function submit(event) {
    event.preventDefault();
    if (!username.trim() || !password) { setError("Enter a username and a password."); return; }
    setBusy(true);
    const answer = await api("POST", "/auth/login", { username: username.trim(), password });
    setBusy(false);
    if (answer.status === 200) signIn(answer.data.token, answer.data.user);
    else setError(answer.status === 401 ? "Wrong username or password." : errorText(answer));
  }

  // a demo account's button fills in its username and the demo password (CORAX_DEMO_PASSWORD's default)
  function fill(user) {
    setUsername(user);
    setPassword("123456");
    passwordInput.current?.focus();
  }

  return (
    <div className="mx-auto mt-[6vh] max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-glass backdrop-blur-md">
      <div className="px-8 pt-12 text-center">
        <h1 className="text-3xl font-medium">Sign In</h1>
        <p className="mt-2 font-medium">Corax Demo - Document Storage Scenario</p>
      </div>
      <div className="px-8 pb-8 pt-2 sm:px-12">
        <form className="mx-auto mt-6 max-w-sm" onSubmit={submit} noValidate>
          <label htmlFor="username" className="sr-only">Username</label>
          <input id="username" className={LINE_INPUT} autoComplete="username" autoFocus placeholder="Username"
                 value={username} onChange={(e) => setUsername(e.target.value)} />
          <label htmlFor="password" className="sr-only">Password</label>
          <input id="password" ref={passwordInput} type="password" className={`${LINE_INPUT} mt-5`} autoComplete="current-password"
                 placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="my-3 min-h-[1.4em] text-center text-[13px] text-no" role="alert">{error}</p>
          <div className="text-center">
            <button type="submit" disabled={busy}
                    className="cursor-pointer rounded-xl border border-transparent bg-accent px-12 py-2.5 text-lg font-medium text-accent-ink transition hover:border-accent/80 hover:bg-transparent hover:text-accent disabled:cursor-progress disabled:opacity-55">
              Sign In
            </button>
          </div>
        </form>
        <div className="mt-8 border-t border-white/10 pt-5">
          <div className="flex flex-wrap justify-center gap-2">
            {accounts.map(([user, label]) => (
              <button key={user} type="button" onClick={() => fill(user)}
                      className="cursor-pointer rounded-lg border border-white/15 bg-glass-button px-2.5 py-1.5 text-left text-[13px] leading-tight transition hover:border-glass-line">
                <b className="block">{user}</b>
                <span className="text-xs text-ink">{label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
