import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期把后端请求代理到 FastAPI（默认 127.0.0.1:8000），
// 避免在后端加 CORS 配置；图片等静态路径一并代理。
const BACKEND = process.env.VITE_BACKEND || 'http://127.0.0.1:8000'

const proxy = {}
for (const p of ['/api', '/uploads', '/kb_images', '/_kb_out', '/review']) {
  proxy[p] = { target: BACKEND, changeOrigin: true }
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy,
  },
})
