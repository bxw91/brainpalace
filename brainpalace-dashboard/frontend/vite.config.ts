/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  build: { outDir: "../brainpalace_dashboard/static", emptyOutDir: true },
  server: {
    proxy: {
      "/dashboard/api": "http://127.0.0.1:8787",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
    css: false,
    // The default 5s timeout is flaky under load (full-suite CI runs time out
    // on otherwise-passing tests). Bump it so a slow machine doesn't false-fail.
    testTimeout: 15000,
  },
});
