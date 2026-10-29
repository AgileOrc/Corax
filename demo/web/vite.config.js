// The build writes index.html and assets/ to dist/, the two paths Envoy sends to the web container
// (deploy/envoy.yaml). "npm run dev" serves the page on port 5173 and sends every API call to the
// running gateway (CORAX_GATEWAY, default http://localhost:8080), so it goes through Envoy and OPA too.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const gateway = process.env.CORAX_GATEWAY || "http://localhost:8080";
// the app's routes, Corax's admin API, and the accounts file the compose file mounts into the web container
const API = ["/auth", "/documents", "/access-requests", "/admin", "/units", "/unit-requests", "/corax", "/assets/accounts.json"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", assetsDir: "assets", emptyOutDir: true },
  server: { port: 5173, proxy: Object.fromEntries(API.map((path) => [path, { target: gateway, changeOrigin: true }])) },
});
