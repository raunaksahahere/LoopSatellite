import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy so the app can fetch /api and /precomputed on one origin in dev.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/precomputed': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
