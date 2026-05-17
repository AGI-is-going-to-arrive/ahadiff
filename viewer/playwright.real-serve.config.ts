import { defineConfig, devices } from '@playwright/test';

const VIEWER_PORT = 18874;
const SERVE_PORT = 18765;

export default defineConfig({
  testDir: './tests/real-serve',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report-real-serve', open: 'never' }]],
  use: {
    baseURL: `http://localhost:${VIEWER_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'en-US',
    timezoneId: 'America/Los_Angeles',
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: {
    command: `pnpm exec vite --port ${VIEWER_PORT} --strictPort`,
    env: {
      ...process.env,
      AHADIFF_DEV_API_ORIGIN: `http://127.0.0.1:${SERVE_PORT}`,
    },
    url: `http://localhost:${VIEWER_PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
