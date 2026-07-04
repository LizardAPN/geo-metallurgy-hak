import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        // In Docker: backend:8000; on host: localhost:8001 (see docker-compose ports).
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
