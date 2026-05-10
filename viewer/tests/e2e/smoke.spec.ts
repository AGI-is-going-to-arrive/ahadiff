import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('smoke', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('root renders and contains AhaDiff or Dashboard heading', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/AhaDiff/i);
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
  });

  test('mobile 375px viewport has no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('hash router diff route renders DiffViewer heading', async ({ page }) => {
    await page.goto('/#/run/test-run/diff');
    await expect(page.getByRole('heading', { name: /diff/i, level: 1 })).toBeVisible();
  });

  test('hash router lesson route renders Lesson heading', async ({ page }) => {
    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router quiz route renders Quiz heading', async ({ page }) => {
    await page.goto('/#/run/test-run/quiz');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router concepts route renders Concepts heading', async ({ page }) => {
    await page.goto('/#/concepts');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router review route renders Review heading', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('review page shows flashcard with mock card data', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();
    await expect(page.locator('.flashcard__concept')).toContainText('learn-from-diff');
  });

  test('review page flip reveals answer and rating buttons', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard__flip-btn')).toBeVisible();
    await page.locator('.flashcard__flip-btn').click();
    await expect(page.locator('.srs-buttons')).toBeVisible();
    const buttons = page.locator('.srs-btn');
    await expect(buttons).toHaveCount(3);
  });

  test('hash router ratchet route renders Ratchet heading', async ({ page }) => {
    await page.goto('/#/ratchet');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('ratchet TSV export uses token-aware API fetch', async ({ page }) => {
    let exportToken: string | undefined;
    await page.route(
      (url) => url.pathname === '/api/export/results',
      (route) => {
        exportToken = route.request().headers()['x-ahadiff-token'];
        expect(new URL(route.request().url()).searchParams.get('format')).toBe('tsv');
        return route.fulfill({
          status: 200,
          contentType: 'text/tab-separated-values',
          body: 'timestamp\trun_id\n',
        });
      },
    );

    await page.goto('/#/ratchet');
    await page.getByRole('button', { name: /Export TSV/i }).click();

    await expect.poll(() => exportToken).toBe('test-token-xxx');
  });

  test('hash router welcome/landing route renders hero', async ({ page }) => {
    await page.goto('/#/welcome');
    await expect(page.locator('.hero')).toBeVisible();
    await expect(page.locator('.hero__title')).toBeVisible();
  });

  test('landing page pipeline steps are visible', async ({ page }) => {
    await page.goto('/#/welcome');
    const steps = page.locator('.step');
    await expect(steps).toHaveCount(5);
  });

  test('landing demo tabs support APG keyboard wrap navigation', async ({ page }) => {
    await page.goto('/#/welcome');
    const raw = page.locator('#tab-raw');
    const aha = page.locator('#tab-aha');

    // Focus raw tab and press ArrowRight -> should activate aha
    await raw.focus();
    await page.keyboard.press('ArrowRight');
    await expect(aha).toHaveAttribute('aria-selected', 'true');
    await expect(aha).toBeFocused();

    // ArrowRight on aha -> should wrap to raw (circular)
    await page.keyboard.press('ArrowRight');
    await expect(raw).toHaveAttribute('aria-selected', 'true');
    await expect(raw).toBeFocused();

    // ArrowLeft on raw -> should wrap to aha (circular)
    await page.keyboard.press('ArrowLeft');
    await expect(aha).toHaveAttribute('aria-selected', 'true');
    await expect(aha).toBeFocused();

    // Home -> first tab (raw)
    await page.keyboard.press('Home');
    await expect(raw).toHaveAttribute('aria-selected', 'true');
    await expect(raw).toBeFocused();

    // End -> last tab (aha)
    await page.keyboard.press('End');
    await expect(aha).toHaveAttribute('aria-selected', 'true');
    await expect(aha).toBeFocused();
  });

  test('hash router settings route renders Settings heading', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('settings page shows tab sidebar and config fields', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByRole('tablist', { name: /settings/i })).toBeVisible();
    await expect(page.getByRole('tab')).toHaveCount(7);
    await expect(page.locator('.settings-field')).not.toHaveCount(0);
    await expect(page.locator('.settings-toggle')).toHaveCount(3);

    await page.getByRole('tab', { name: /provider/i }).click();
    await expect(page.locator('.provider-card').first()).toBeVisible();

    await page.getByRole('tab', { name: /audit/i }).click();
    await expect(page.locator('.audit-table')).toBeVisible();
    await expect(page.locator('.audit-table')).toContainText('lesson_generate');

    await page.getByRole('tab', { name: /account/i }).click();
    await expect(page.locator('.doctor-check')).not.toHaveCount(0);
  });

  test('settings tabs expose stable ARIA panels and keyboard navigation', async ({ page }) => {
    await page.goto('/#/settings');

    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(7);
    const controls = await tabs.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('aria-controls') ?? ''),
    );
    for (const id of controls) {
      expect(id).toMatch(/^spanel-/);
      await expect(page.locator(`#${id}`)).toHaveCount(1);
    }

    const privacyTab = page.getByRole('tab', { name: /privacy/i });
    await expect(privacyTab).toHaveAttribute('aria-selected', 'true');
    await privacyTab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: /audit/i })).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('End');
    await expect(page.getByRole('tab', { name: /integrations/i })).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('Home');
    await expect(page.getByRole('tab', { name: /account/i })).toHaveAttribute('aria-selected', 'true');
  });

  test('settings shows local fallback states for failed and empty resources', async ({ page }) => {
    let graphStatusRequests = 0;
    await page.unroute((url) => url.pathname === '/api/config');
    await page.unroute((url) => url.pathname === '/api/providers');
    await page.unroute((url) => url.pathname === '/api/audit');
    await page.unroute((url) => url.pathname === '/api/install/targets');
    await page.unroute((url) => url.pathname === '/api/graph/status');
    await page.route(
      (url) => url.pathname === '/api/config',
      (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }),
    );
    await page.route(
      (url) => url.pathname === '/api/providers',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ providers: [] }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/audit',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            entries: [],
            total: 0,
            limit: 20,
            offset: 0,
            page: 1,
            has_more: false,
          }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/install/targets',
      (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }),
    );
    await page.route(
      (url) => url.pathname === '/api/graph/status',
      (route) => {
        graphStatusRequests += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            enabled: true,
            source_exists: true,
            has_graph: true,
            freshness: 'fresh',
            node_count: 3,
            edge_count: 2,
            source_path: '.ahadiff/graphify/graph.json',
            provenance: null,
          }),
        });
      },
    );

    await page.goto('/#/settings');
    await expect(
      page.locator('#spanel-privacy').getByText('Configuration is unavailable right now.'),
    ).toBeVisible();
    expect(graphStatusRequests).toBe(0);

    await page.getByRole('tab', { name: /provider/i }).click();
    await expect(page.getByText('No providers configured')).toBeVisible();

    await page.getByRole('tab', { name: /audit/i }).click();
    await expect(page.getByText('No audit entries yet')).toBeVisible();

    await page.getByRole('tab', { name: /integrations/i }).click();
    await expect(
      page.locator('#spanel-integrations').getByText('Integration targets are unavailable right now.'),
    ).toBeVisible();
    await expect(page.locator('.graphify-card').filter({ hasText: 'Graphify source' })).toBeVisible();
    expect(graphStatusRequests).toBe(1);
  });

  test('hash router onboarding route renders stepper', async ({ page }) => {
    await page.goto('/#/onboarding');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.stepper__step')).toHaveCount(4);
  });

  test('hash router guide route renders workflow section and command blocks', async ({ page }) => {
    await page.goto('/#/guide');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.guide')).toBeVisible();
    await expect(page.locator('.guide-workflow')).toBeVisible();
    await expect(page.locator('.guide-card').first()).toBeVisible();
  });

  test('guide page shows copy button on command blocks', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            (window as typeof window & { __ahadiffCopiedText?: string })
              .__ahadiffCopiedText = value;
          },
        },
      });
    });
    await page.goto('/#/guide');
    const copyButton = page.locator('.command-block__copy-btn').first();
    await expect(copyButton).toBeVisible();
    await copyButton.click();
    await expect(copyButton).toHaveAccessibleName(/Copied!/);
    await expect.poll(
      () => page.evaluate(
        () => (window as typeof window & { __ahadiffCopiedText?: string })
          .__ahadiffCopiedText,
      ),
    ).toBe('pip install ahadiff');
  });

  test('legacy /#/skills redirects to /#/guide', async ({ page }) => {
    await page.goto('/#/skills');
    await page.waitForURL(/#\/guide/);
    expect(page.url()).toMatch(/#\/guide$/);
    await expect(page.locator('.guide')).toBeVisible();
  });
});
