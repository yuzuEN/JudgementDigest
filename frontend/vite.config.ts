/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 開發時 /api 轉給後端（uvicorn，預設 8000 埠）；正式環境由 nginx 轉（見 frontend/nginx.conf）
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
