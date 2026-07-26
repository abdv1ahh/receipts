import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The marketing site. A sibling Vite project to `frontend/`, not an npm workspace — this is a
// Python repository with two small front ends, and converting to workspaces to host one extra
// site is more machinery than the problem needs (docs/plan.md §6).
//
// `base: "/site/"` because FastAPI serves the built bundle under /site while the app owns "/".
// Phase 8 puts the site on the apex domain and the app on a subdomain, which is the split the
// brief implies ("a separate public application"); until then this keeps both verifiable on one
// origin without the site stealing routes like /radar from the app.
export default defineConfig({
  plugins: [react()],
  base: "/site/",
  server: {
    port: 5174,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // The site is read top-to-bottom in one sitting; splitting it into a dozen chunks would trade
    // a smaller first parse for a stack of round trips. One vendor chunk, one app chunk.
    rollupOptions: {
      output: {
        manualChunks: (id) => (id.includes("node_modules") ? "vendor" : undefined),
      },
    },
  },
});
