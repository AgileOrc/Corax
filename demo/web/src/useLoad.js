import { useCallback, useEffect, useRef, useState } from "react";

// Runs load() when the page opens and on reload(); data is what it returned, null while loading.
// An answer that comes back after the page closed or reloaded again is dropped.
export function useLoad(load) {
  const [data, setData] = useState(null);
  const [round, setRound] = useState(0);
  const started = useRef(null);  // one request per round, also when StrictMode runs the effect twice
  useEffect(() => {
    let current = true;
    if (started.current?.round !== round) started.current = { round, promise: load() };
    started.current.promise.then((result) => { if (current) setData(result); });
    return () => { current = false; };
  }, [round]);  // not load: each page passes its own, fixed for the page's life
  const reload = useCallback(() => setRound((n) => n + 1), []);
  return [data, reload];
}
