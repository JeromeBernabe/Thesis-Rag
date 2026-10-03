import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
// From `vitest/config`, not `vite`: the `test` block is not part of Vite's own
// config type, so importing from Vite makes `tsc -b` reject the file.
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // Tauri serves the built assets from a file:// URL in production, so every
  // asset reference has to be relative rather than rooted at "/".
  base: './',
  // Vite's dev server must not try to swallow the Tauri IPC custom protocol.
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // src-tauri is watched by cargo, not vite.
      ignored: ['**/src-tauri/**'],
    },
  },
  // Fail the build rather than the browser on a type error.
  build: {
    target: 'esnext',
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    minify: process.env.TAURI_ENV_DEBUG ? false : 'esbuild',
    chunkSizeWarningLimit: 1600,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['src/test/**', 'src/**/*.d.ts', 'src/main.tsx'],
    },
  },
})