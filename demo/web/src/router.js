import { useEffect, useState } from "react";

// Hash routes (#/documents): Envoy sends only "/" and "/assets/" to the web container, every other
// path to the app, so the page's own routes must stay after the "#".
export function useHash() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const changed = () => setHash(location.hash || "#/");
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  return hash;
}

export const go = (hash) => { location.hash = hash; };

// [Page, params] of the first route whose pattern matches, else [null, []]
export function match(routes, hash) {
  for (const [pattern, Page] of routes) {
    const found = hash.match(pattern);
    if (found) return [Page, found.slice(1).filter((part) => part !== undefined)];
  }
  return [null, []];
}
