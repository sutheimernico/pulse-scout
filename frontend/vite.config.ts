import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Same shape as equity-scout: relative asset URLs so FastAPI can serve dist/ from "/", and
// during `npm run dev` the /api calls go to the real server on :8430 — never to a mock.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8430" } },
  build: { outDir: "dist", emptyOutDir: true },
});
