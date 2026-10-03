import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against the built frontend.
 *
 * These run against `vite preview` rather than the Tauri shell, because the Tauri
 * window has no address bar for Playwright to attach to. That covers the UI - which
 * is where the regressions worth catching live - and the Rust side is covered by
 * its own 70 unit tests. What this cannot catch is the IPC boundary, which is
 * covered by the real smoke run in `desktop/scripts/verify.ps1`.
 *
 * The API module is stubbed at the network boundary, so no test needs Ollama, a
 * GPU or a populated database.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['html']] : [['list']],
  use: {
    // Matches the host `vite preview` actually binds. On this machine `localhost`
    // resolves to ::1 while 127.0.0.1 is refused, so the two must not be mixed.
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})