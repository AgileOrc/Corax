import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";


// A dialog over the page: Escape or a click on the backdrop closes it.
export function Modal({ title, onClose, children, width = "max-w-[660px]", titleClass = "text-xl font-semibold", headClass = "mb-4" }) {
  const box = useRef(null);
  useEffect(() => {
    const key = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    (box.current?.querySelector("input, textarea, button") || box.current)?.focus();
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  // on <body>, so a blurred box around the button cannot trap or clip it
  return createPortal(
    <div className="fixed inset-0 z-20 grid place-items-center p-4" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
           className={`flex w-full ${width} max-h-[90vh] min-h-[226px] flex-col justify-center-safe overflow-y-auto rounded-xl border border-white/10 bg-glass/45 px-10 py-8 shadow-2xl backdrop-blur-xl`}>
        <div className={`${headClass} flex items-center justify-between gap-3`}>
          <h2 className={titleClass}>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" title="Close" className="cursor-pointer text-ink transition hover:text-accent">
            <svg viewBox="0 0 24 24" aria-hidden="true" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
