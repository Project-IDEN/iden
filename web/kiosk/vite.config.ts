import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built into kiosk/server's image and served by it on localhost. In development
// Vite serves the page and passes /api to the kiosk server.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: { "/api": "http://localhost:8080" },
  },
});
