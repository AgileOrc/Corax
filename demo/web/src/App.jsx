// Corax Demo: the web frontend of the document app (demo/app), protected by Corax. Every API call
// goes through the gateway (Envoy -> OPA -> the AI risk check) like any other client's; only the page's
// files and POST /auth/login skip the check.
import { useCallback, useEffect, useMemo, useState } from "react";

import { onApiTrouble } from "./api.js";
import { useToast } from "./components/Toasts.jsx";
import { Button, Card } from "./components/ui.jsx";
import { place, titled } from "./format.js";
import Document from "./pages/Document.jsx";
import Documents from "./pages/Documents.jsx";
import Login from "./pages/Login.jsx";
import MyRequests from "./pages/MyRequests.jsx";
import Shared from "./pages/Shared.jsx";
import Units from "./pages/Units.jsx";
import Grant from "./pages/admin/Grant.jsx";
import Request from "./pages/admin/Request.jsx";
import Requests from "./pages/admin/Requests.jsx";
import Rules from "./pages/admin/Rules.jsx";
import Suggestions from "./pages/admin/Suggestions.jsx";
import UnitRequest from "./pages/admin/UnitRequest.jsx";
import UnitRequests from "./pages/admin/UnitRequests.jsx";
import { go, match, useHash } from "./router.js";
import { forgetAll, home, session } from "./session.js";
import { SessionContext } from "./SessionContext.jsx";

const ROUTES = [
  [/^#\/login$/, Login],
  [/^#\/documents$/, Documents],
  [/^#\/documents\/([\w-]+)$/, Document],
  [/^#\/shared$/, Shared],
  [/^#\/requests$/, MyRequests],
  [/^#\/units$/, Units],
  [/^#\/rules$/, Rules],
  [/^#\/grant$/, Grant],
  [/^#\/suggestions$/, Suggestions],
  [/^#\/unit-requests$/, UnitRequests],
  [/^#\/unit-requests\/(\d+)$/, UnitRequest],
  [/^#\/admin(?:\/(pending|granted|decided|all))?$/, Requests],
  [/^#\/admin\/request\/(\d+)$/, Request],
];

const ADMIN_LINKS = [["#/admin", "Access requests"], ["#/unit-requests", "Unit requests"], ["#/suggestions", "Suggested access"],
                     ["#/grant", "Give access"], ["#/rules", "Access granted"], ["#/documents", "Documents"]];
const EMPLOYEE_LINKS = [["#/documents", "Documents"], ["#/shared", "Shared with me"], ["#/units", "Ask for a unit"], ["#/requests", "My requests"]];

function TopBar({ user, hash, onSignOut }) {
  const admin = user.kind === "admin";
  return (
    <header className="sticky top-0 z-10 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line bg-panel px-4 py-2.5 sm:flex-nowrap sm:px-6">
      <a href={home(user)} className="whitespace-nowrap text-base font-semibold text-ink hover:no-underline">Corax Demo</a>
      <nav className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto sm:flex-1">
        {(admin ? ADMIN_LINKS : EMPLOYEE_LINKS).map(([href, label]) => (
          <a key={href} href={href}
             className={`whitespace-nowrap rounded-lg px-3 py-1.5 font-medium hover:no-underline ${hash.startsWith(href) ? "bg-accent-soft text-accent" : "text-muted hover:bg-panel-2 hover:text-ink"}`}>
            {label}
          </a>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2.5 text-sm text-muted">
        <span className="hidden md:inline">
          <b className="font-semibold text-ink">{user.name}</b>
          {admin ? " · reviews access requests" : ` · ${titled(user.role)}, ${titled(user.department)} · ${place(user.site, user.region)}`}
        </span>
        <Button variant="ghost" size="sm" onClick={() => onSignOut()}>Sign out</Button>
      </div>
    </header>
  );
}

export default function App() {
  const hash = useHash();
  const toast = useToast();
  const [user, setUser] = useState(() => session.user);

  const signOut = useCallback((message) => {
    session.clear();
    forgetAll();
    setUser(null);
    if (message) toast(message);
    go("#/login");
  }, [toast]);

  const signIn = useCallback((token, signedIn) => {
    session.save(token, signedIn);
    setUser(signedIn);
    go(home(signedIn));
  }, []);

  useEffect(() => {
    onApiTrouble({
      expired: () => signOut("Your session has ended. Please sign in again."),
      unreachable: () => toast("The gateway is not reachable.", "no"),
    });
  }, [signOut, toast]);

  // signed out: only the sign-in page; signed in: no sign-in page
  const signedIn = session.valid();
  const redirect = !signedIn && hash !== "#/login" ? "#/login"
    : signedIn && ["#/", "#/login", "#"].includes(hash) ? home(session.user) : null;
  useEffect(() => {
    if (!redirect) return;
    if (!signedIn) session.clear();
    location.replace(redirect);
  }, [redirect, signedIn]);

  const context = useMemo(() => ({ user, signIn, signOut }), [user, signIn, signOut]);
  if (redirect) return null;

  const [Page, params] = match(ROUTES, hash);
  return (
    <SessionContext.Provider value={context}>
      <div className="flex min-h-screen flex-col">
        {signedIn && user && <TopBar user={user} hash={hash} onSignOut={signOut} />}
        {/* the width of every page: wide, with a margin that grows on larger screens */}
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-8 lg:px-12">
          {Page
            ? <Page key={hash} params={params} />
            : <Card><p className="py-8 text-center text-muted">Page not found. <a href="#/documents">Documents</a></p></Card>}
        </main>
        {signedIn && (
          <footer className="px-6 pb-6 pt-4 text-center text-[13px] text-muted">
            Every request goes through the gateway: Envoy → OPA (the policy) → the AI risk check. Appeals and generated rules: Corax console on port 8090.
          </footer>
        )}
      </div>
    </SessionContext.Provider>
  );
}
