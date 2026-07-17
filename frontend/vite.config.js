import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built bundle is served by FastAPI StaticFiles at "/"; API is same-origin under /api.
// During `npm run dev`, proxy /api to the running compose stack on :8000.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
