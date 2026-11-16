import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// 开发时把 /api 与 /media 代理到本机后端（./wardrobe dev），浏览器看到的仍是同源
const backend = process.env.WARDROBE_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/media": { target: backend, changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: { environment: "jsdom", include: ["tests/**/*.spec.ts"] },
});
