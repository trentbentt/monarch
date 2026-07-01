import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Isolated from vite.config.js (no PWA plugin in tests). CSS imports become
// no-ops so we can render components in a node env.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    css: false,
    globals: true,
    include: ["src/**/*.test.{js,jsx}"],
  },
});
