import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The interface talks only to the Overturn API. In development the API runs on :8000
// (uvicorn --factory overturn.api.app:app_from_env) and Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
