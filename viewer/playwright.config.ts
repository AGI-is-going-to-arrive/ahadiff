import { defineConfig, devices } from '@playwright/test';

const viewports = [
  // 360x640 = smallest mainstream Android (lang-switcher visible at >=374px breakpoint)
  { name: 'phone-narrow', width: 360, height: 640 },
  { name: 'mobile', width: 375, height: 667 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'laptop', width: 1024, height: 768 },
  { name: 'desktop', width: 1440, height: 900 },
];

const browsers = [
  { name: 'chromium', device: devices['Desktop Chrome'] },
  { name: 'firefox', device: devices['Desktop Firefox'] },
  { name: 'webkit', device: devices['Desktop Safari'] },
];

const devServerPort = Number(process.env.AHADIFF_VIEWER_E2E_PORT ?? '5173');
const devServerUrl = `http://localhost:${devServerPort}`;
const reuseExistingDevServer = !process.env.CI && process.env.AHADIFF_VIEWER_E2E_PORT === undefined;

const projects = viewports.flatMap((v) =>
  browsers.map((b) => ({
    name: `${b.name}-${v.name}`,
    use: {
      ...b.device,
      viewport: { width: v.width, height: v.height },
    },
  })),
);

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: devServerUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'en-US',
    timezoneId: 'America/Los_Angeles',
  },
  projects,
  webServer: {
    command: `pnpm exec vite --port ${devServerPort} --strictPort`,
    url: devServerUrl,
    reuseExistingServer: reuseExistingDevServer,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
