/// <reference types="vitest/config" />
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// vite.config.ts is loaded as an ES module (package.json has "type":
// "module"), where CommonJS's __dirname genuinely does not exist -- the
// standard ESM-safe replacement derives it from import.meta.url instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Dev-only proxy so `npm run dev` (port 5173) can talk to the API server on
// :8000 without CORS. In production the same nginx origin serves both the
// built SPA and the API proxy -- see infra/gateway.nginx.conf -- so no base
// URL config is needed on either side; every fetch in this app is relative.
//
// 127.0.0.1, not localhost: on a dual-stack Mac, "localhost" can resolve to
// ::1 first, which may hit an entirely different service bound to that port
// on the IPv6 wildcard address (confirmed while testing this scaffold --
// some other local process answers on *:8000 over IPv6 with an unrelated
// response). Same class of ambiguity .env.example already documents for
// DATABASE_URL; pinning the literal IPv4 address sidesteps it here too.
const API_TARGET = "http://127.0.0.1:8000";
const PROXIED_PREFIXES = [
  "/dashboard",
  "/eval-runs",
  "/agents",
  "/eval-suites",
  "/auth",
  "/diff-runs",
  "/load-runs",
  "/mining",
  "/ci",
];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [prefix, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
  test: {
    environment: "jsdom",
    globals: false,
  },
});
