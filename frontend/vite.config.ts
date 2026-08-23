import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 前端只消费聚合 API（http://127.0.0.1:8000），CORS 已在后端放行 5173。
// 若需同源代理，可改为 proxy 并让 VITE_API_BASE_URL 指向同源路径。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
