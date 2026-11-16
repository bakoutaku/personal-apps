import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const frontendDir = fileURLToPath(new URL('.', import.meta.url));
// 只开放虚构的模拟数据目录；backend、docs、参考图不进入开发服务范围。
const mocksDir = fileURLToPath(new URL('../contracts/mocks', import.meta.url));

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: { '@mocks': mocksDir },
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    fs: { strict: true, allow: [frontendDir, mocksDir] },
    // 联调：同源代理到本机后端。changeOrigin 只改 Host（后端按 127.0.0.1:49173 校验），
    // 浏览器的 Origin / Referer 原样转发；后端用 --dev-origin http://127.0.0.1:5174 登记。
    proxy: {
      '/api/v1': { target: 'http://127.0.0.1:49173', changeOrigin: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4174,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
