import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 新项目 FastAPI 的路由不含 /api 前缀（/health、/predict/*、/explain/* ...），
// 因此按前缀逐个代理到 8000，避免与前端自身路由冲突。
const API_PREFIXES = [
  '/health',
  '/model',
  '/predict',
  '/explain',
  '/monitor',
  '/features',
  '/finance',
  '/alerts',
  '/risk',
  '/datasources',
  '/enterprise',
]

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PREFIXES.map((prefix) => [
        prefix,
        {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          // 前缀会遮蔽同名 SPA 路由（如 /enterprises 命中 /enterprise 前缀、
          // /alerts 直接返回 JSON）：浏览器文档请求改服务 index.html（SPA 接管路由），仅 XHR/fetch 走 API
          bypass: (req) =>
            (req.headers.accept ?? '').includes('text/html')
              ? '/index.html'
              : undefined,
        },
      ]),
    ),
    watch: {
      // 编辑器/写盘工具产生临时文件，避免 EBUSY 导致 watcher 崩溃
      ignored: ['**/*.tmp', '**/.git/**', '**/dist/**', '**/.venv/**'],
    },
  },
})
