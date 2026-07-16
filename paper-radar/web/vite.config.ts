import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Expose both our VITE_* names and Supabase's NEXT_PUBLIC_* names, so the
  // values copied straight from the Supabase dashboard work without renaming.
  envPrefix: ["VITE_", "NEXT_PUBLIC_"],
  build: {
    // Pinned because vercel.json's SPA rewrite excludes exactly "assets/" so
    // missing hashed chunks 404 instead of serving index.html; renaming this
    // must update that rewrite in lockstep.
    assetsDir: "assets",
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
