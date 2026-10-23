// Frontend tests (npm test). jsdom gives React a browser-like document; network calls are mocked per test.
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.tsx', 'src/**/*.test.ts'],
    restoreMocks: true,
  },
})
