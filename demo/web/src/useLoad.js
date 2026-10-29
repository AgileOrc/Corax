import { useCallback, useEffect, useState } from "react";

// Runs load() when the page opens and on reload(); data is what it returned, null while loading.
// An answer that comes back after the page closed or reloaded again is dropped.
export function useLoad(load) {
  const [data, setData] = useState(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    let current = true;
    load().then((result) => { if (current) setData(result); });
    return () => { current = false; };
  }, [round]);  // not load: each page passes its own, fixed for the page's life
  const reload = useCallback(() => setRound((n) => n + 1), []);
  return [data, reload];
}
