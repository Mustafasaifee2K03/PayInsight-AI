import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // xfwd: forward the browser's address (X-Forwarded-For) so per-client rate limits and audit IPs work
      "/api": { target: "http://127.0.0.1:8000", xfwd: true },
      "/health": { target: "http://127.0.0.1:8000", xfwd: true },
    },
  },
  build: { chunkSizeWarningLimit: 700, rollupOptions: { output: { manualChunks: { recharts: ["recharts"], react: ["react", "react-dom"] } } } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
} as any);
