import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  const pages: [string, string][] = [
    ['/', 'Dashboard'],
    ['/#/welcome', 'Landing'],
    ['/#/run/test-run/lesson', 'Lesson'],
    ['/#/run/test-run/diff', 'Diff'],
    ['/#/run/test-run/quiz', 'Quiz'],
    ['/#/review', 'Review'],
    ['/#/ratchet', 'Ratchet'],
    ['/#/concepts', 'Concepts'],
    ['/#/settings', 'Settings'],
    ['/#/onboarding', 'Onboarding'],
    ['/#/skills', 'Skills'],
    ['/#/nonexistent-path', 'NotFound'],
  ];

  for (const [path, label] of pages) {
    test(`${label} page passes axe-core audit`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await expect(
        page.locator('main, [role="main"], h1').first(),
      ).toBeVisible({ timeout: 5_000 });
      const results = await new AxeBuilder({ page })
        .disableRules(['color-contrast'])
        .analyze();
      expect(results.violations).toEqual([]);
    });
  }

  const learnTaskStates = [
    {
      label: 'running',
      task: {
        task_id: 'task-a11y-run',
        task_type: 'learn',
        status: 'running',
        progress: { current: 5, total: 10, message: 'Generating lesson...' },
        result_summary: null,
        error: null,
        error_code: null,
        created_at: '2026-05-02T00:00:00Z',
        started_at: '2026-05-02T00:00:01Z',
        completed_at: null,
        elapsed_seconds: null,
        recovery_hint: null,
      },
    },
    {
      label: 'failed',
      task: {
        task_id: 'task-a11y-fail',
        task_type: 'learn',
        status: 'failed',
        progress: { current: 3, total: 10, message: 'Failed' },
        error: 'Network timeout',
        error_code: 'network_error',
        recovery_hint: 'retry',
        result_summary: null,
        created_at: '2026-05-02T00:00:00Z',
        started_at: '2026-05-02T00:00:01Z',
        completed_at: '2026-05-02T00:00:10Z',
        elapsed_seconds: 9,
      },
    },
    {
      label: 'completed',
      task: {
        task_id: 'task-a11y-done',
        task_type: 'learn',
        status: 'completed',
        progress: { current: 10, total: 10, message: 'Done' },
        result_summary: { run_id: 'test-run', status: 'baseline', overall: 92, verdict: 'PASS', warnings: [] },
        error: null,
        error_code: null,
        created_at: '2026-05-02T00:00:00Z',
        started_at: '2026-05-02T00:00:01Z',
        completed_at: '2026-05-02T00:00:30Z',
        elapsed_seconds: 29,
        recovery_hint: null,
      },
    },
  ];

  for (const { label, task } of learnTaskStates) {
    test(`Dashboard with learn-task ${label} state passes axe-core audit`, async ({ page }) => {
      await page.route(
        (url) => url.pathname === '/api/tasks',
        (route) =>
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ tasks: [task] }),
          }),
      );
      await page.goto('/');
      await page.waitForLoadState('networkidle');
      await expect(
        page.locator('main, [role="main"], h1').first(),
      ).toBeVisible({ timeout: 5_000 });
      const results = await new AxeBuilder({ page })
        .disableRules(['color-contrast'])
        .analyze();
      expect(results.violations).toEqual([]);
    });
  }
});
