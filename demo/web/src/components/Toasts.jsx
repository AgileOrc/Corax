import { createContext, useCallback, useContext, useState } from "react";

const ToastContext = createContext(() => {});
export const useToast = () => useContext(ToastContext);
let counter = 0;

// Short messages in the corner, gone after a few seconds. kind "no" for an error.
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const toast = useCallback((text, kind = "") => {
    const id = ++counter;
    setToasts((all) => [...all, { id, text, kind }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 4500);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {/* above the light and dark switch in the corner */}
      <div className="fixed bottom-18 right-4 z-30 grid gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`max-w-[360px] rounded-lg px-3.5 py-2.5 text-sm shadow-card ${t.kind === "no" ? "bg-no text-white" : "bg-ink text-panel"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
