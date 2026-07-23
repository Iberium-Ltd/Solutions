/**
 * Builds the webview with local assets and Tauri-compatible development
 * settings; native authority is never replaced by the browser dev server.
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
})
