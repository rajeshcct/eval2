import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// EvalMind frontend — Phase III.
// Dev server intentionally pinned to port 5173, matching the CORS origins
// backend/app/main.py already allows (http://localhost:5173 /
// http://127.0.0.1:5173). Changing this port means updating the backend's
// CORS list too, or requests from `npm run dev` will be rejected.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
});
