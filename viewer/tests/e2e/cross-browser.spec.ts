import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('cross-browser corner cases', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await installServeMock(page);
  });

  test('rapid locale toggle settles to final state', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const switcher = page.getByRole('group', { name: /Language|语言/i });
    const zhBtn = switcher.getByRole('button', { name: '简体中文' });
    const enBtn = switcher.getByRole('button', { name: 'English' });

    // Rapid toggle: en -> zh-CN -> en -> zh-CN without awaiting intermediate UI
    await zhBtn.click();
    await enBtn.click();
    await zhBtn.click();
    await enBtn.click();

    // Final state should be en
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);
    await expect(enBtn).toHaveAttribute('aria-pressed', 'true');

    expect(errors).toHaveLength(0);
  });

  test('rapid sequential navigation produces no JS errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Navigate rapidly: Dashboard -> Lesson -> Quiz -> Concepts
    await page.goto('/#/run/test-run/lesson');
    await page.goto('/#/run/test-run/quiz');
    await page.goto('/#/concepts');

    // Final page should render Concepts heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Concept/i);

    expect(errors).toHaveLength(0);
  });

  test('dashboard fetch error shows alert then recovers on retry navigation', async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Override /api/runs to fail
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'error' }),
    );

    await page.goto('/');

    // Should show error alert
    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible();

    // Remove the failing route and re-add the success route
    await page.unroute((url) => url.pathname === '/api/runs');
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ runs: [] }),
        }),
    );

    // Navigate away and back to trigger refetch
    await page.goto('/#/concepts');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);

    // Error alert should be gone, empty state should show
    await expect(page.locator('.dashboard__empty')).toBeVisible();

    expect(errors).toHaveLength(0);
  });

  test('empty runs list renders Dashboard empty hint', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Default mock returns { runs: [] }
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);
    // Verify empty state hint text is visible
    const emptyHint = page.locator('.dashboard__empty-hint');
    await expect(emptyHint).toBeVisible();
    await expect(emptyHint).toHaveText(/ahadiff learn/);

    expect(errors).toHaveLength(0);
  });

  test('ScaffoldingTabs keyboard navigation moves focus correctly', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const tablist = page.getByRole('tablist', { name: /Lesson|/i });
    await expect(tablist).toBeVisible();

    // Initial state: "Full" tab is selected
    const fullTab = tablist.getByRole('tab', { name: /Full/i });
    const hintTab = tablist.getByRole('tab', { name: /Hint/i });
    const compactTab = tablist.getByRole('tab', { name: /Compact/i });

    await expect(fullTab).toHaveAttribute('aria-selected', 'true');

    // Focus the active tab then use ArrowRight to move
    await fullTab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(hintTab).toHaveAttribute('aria-selected', 'true');
    await expect(hintTab).toBeFocused();

    await page.keyboard.press('ArrowRight');
    await expect(compactTab).toHaveAttribute('aria-selected', 'true');
    await expect(compactTab).toBeFocused();

    // ArrowLeft should move back
    await page.keyboard.press('ArrowLeft');
    await expect(hintTab).toHaveAttribute('aria-selected', 'true');
    await expect(hintTab).toBeFocused();

    expect(errors).toHaveLength(0);
  });

  test('long lesson content does not produce horizontal overflow', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Override lesson endpoint with very long content
    const longLine = 'A'.repeat(2000);
    const longContent = `# Very Long Lesson\n\n${longLine}\n\nEnd of lesson.`;
    await page.route(
      (url) => /^\/api\/run\/[^/]+\/lesson$/.test(url.pathname),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'test-run',
            kind: 'lesson',
            content: longContent,
            truncated: false,
          }),
        }),
    );

    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Wait for lesson content to render
    await expect(page.locator('.lesson-markdown')).toBeVisible();

    // Check that document-level horizontal overflow does not exist
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    expect(errors).toHaveLength(0);
  });

  test('mobile viewport shows bottom nav bar with navigation links', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // At mobile width (<768px), sidebar becomes fixed bottom nav
    const nav = page.getByRole('navigation', { name: /Navigation|导航/i });
    await expect(nav).toBeVisible();

    // The nav should contain Dashboard link at minimum
    const dashboardLink = nav.locator('a', { hasText: /Dashboard/ });
    await expect(dashboardLink).toBeVisible();

    // Concepts link should also be visible in bottom nav
    const conceptsLink = nav.locator('a', { hasText: /Concepts/ });
    await expect(conceptsLink).toBeVisible();

    // Verify no horizontal overflow at mobile width
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    expect(errors).toHaveLength(0);
  });
});
