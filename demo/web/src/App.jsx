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
    <header className="sticky top-0 z-10 flex flex-wrap items-center gap-x-5 border-b border-line px-4 bg-panel sm:flex-nowrap lg:px-8">
      <a href={home(user)} className="whitespace-nowrap py-3 text-base font-semibold text-ink hover:no-underline">Corax Demo</a>
      {/* nav */}
      <nav className="order-3 flex w-full gap-1 self-stretch overflow-x-auto sm:order-none sm:w-auto sm:flex-1">
        {(admin ? ADMIN_LINKS : EMPLOYEE_LINKS).map(([href, label]) => (
          <a key={href} href={href}
             className={`relative flex items-center whitespace-nowrap px-5 py-5 font-medium hover:no-underline after:absolute after:inset-x-1 after:bottom-0 after:h-[3px] after:rounded-t-full ${hash.startsWith(href) ? "text-accent after:bg-accent" : "text-muted hover:text-ink"}`}>
            {label}
          </a>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-7 py-2 text-sm text-muted">
        <span className="hidden md:inline">
          <b className="font-semibold text-ink">{user.name}</b>
          {admin ? " · reviews access requests" : `  |  ${titled(user.role)} - ${titled(user.department)}  |  ${place(user.site, user.region)}`}
        </span>
        <Button variant="ghost" size="md" className="bg-accent/5! border-accent/15!" onClick={() => onSignOut()}>Sign out</Button>
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
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-8 lg:px-12">
          {Page
            ? <Page key={hash} params={params} />
            : <Card><p className="py-8 text-center text-muted">Page not found. <a href="#/documents">Documents</a></p></Card>}
        </main>
      </div>
    </SessionContext.Provider>
  );
}
