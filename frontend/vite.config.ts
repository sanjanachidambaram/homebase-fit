import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In dev, forward API calls and content media to the FastAPI backend on port 8000.
    proxy: {
      '/api': 'http://localhost:8000',
      '/content': 'http://localhost:8000',
    },
  },
})
