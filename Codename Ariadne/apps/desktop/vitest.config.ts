import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    include: ['src/test/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://127.0.0.1:1420/',
      },
    },
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    clearMocks: true,
    restoreMocks: true,
    mockReset: true,
  },
})
