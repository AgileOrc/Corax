import { useEffect, useRef } from "react";

import { Button } from "./ui.jsx";

// A dialog over the page: Escape or a click on the backdrop closes it.
export function Modal({ title, onClose, children }) {
  const box = useRef(null);
  useEffect(() => {
    const key = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    (box.current?.querySelector("input, textarea, button") || box.current)?.focus();
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-black/45 p-4" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
           className="w-full max-w-[560px] rounded-xl bg-panel p-5 shadow-2xl">
        <div className="mb-2.5 flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">Close</Button>
        </div>
        {children}
      </div>
    </div>
  );
}
