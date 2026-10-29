import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import { ToastProvider } from "./components/Toasts.jsx";
import { applyTheme, storedTheme, ThemeSwitch } from "./Theme.jsx";
// Poppins, served with the page's own files (the CSP allows fonts from 'self' only); Latin, the weights the pages use
import "@fontsource/poppins/latin-400.css";
import "@fontsource/poppins/latin-500.css";
import "@fontsource/poppins/latin-600.css";
import "@fontsource/poppins/latin-700.css";
import "./styles.css";

// the theme the user chose before, set before the first render
applyTheme(storedTheme());

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ToastProvider>
      <App />
      <ThemeSwitch />
    </ToastProvider>
  </StrictMode>,
);
