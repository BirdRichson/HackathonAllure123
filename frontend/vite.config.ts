import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В docker-compose бэкенд доступен как http://backend:8000, локально — http://localhost:8000.
const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/ws": { target: apiTarget.replace(/^http/, "ws"), ws: true },
    },
  },
});
