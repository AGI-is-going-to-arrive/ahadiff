import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

async function mockSingleSearchResult(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/search',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          results: [
            {
              source_table: 'concepts',
              primary_key: 'concept-mobile-preview',
              snippet: 'mobile preview result',
              rank: 0.95,
              href: '#/concepts',
            },
          ],
          next_cursor: null,
        }),
      }),
  );
}

test.describe('SearchOverlay browser regressions', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await installServeMock(page);
  });

  test('mobile preview back and Escape return to results without leaking focus', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await mockSingleSearchResult(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.keyboard.press('Control+K');

    const dialog = page.getByRole('dialog', { name: /Search|搜索/i });
    const input = page.locator('#search-overlay-input');
    await expect(dialog).toBeVisible();
    await expect(input).toBeFocused();

    await input.fill('preview');
    const resultButton = page.locator('.search-overlay__result-btn').first();
    await expect(resultButton).toContainText('mobile preview result');

    await resultButton.focus();
    await page.keyboard.press('Tab');
    await expect(input).toBeFocused();

    await resultButton.click();
    await expect(page.locator('.search-overlay__panel')).toHaveAttribute('data-mobile-view', 'preview');
    const backButton = page.getByRole('button', { name: /Back to results/i });
    await expect(backButton).toBeVisible();
    await expect(backButton).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(dialog).toBeVisible();
    await expect(page.locator('.search-overlay__panel')).not.toHaveAttribute('data-mobile-view', 'preview');
    await expect(input).toBeFocused();

    await resultButton.click();
    await expect(backButton).toBeFocused();
    await backButton.click();
    await expect(input).toBeFocused();
  });

  test('Escape closes from results mode and restores trigger focus', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockSingleSearchResult(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const searchButton = page.getByRole('button', { name: /Open search/i });
    await searchButton.focus();
    await searchButton.click();

    const dialog = page.getByRole('dialog', { name: /Search|搜索/i });
    const input = page.locator('#search-overlay-input');
    await expect(dialog).toBeVisible();
    await expect(input).toBeFocused();

    await input.fill('preview');
    await expect(page.locator('.search-overlay__result-btn').first()).toContainText('mobile preview result');
    await page.keyboard.press('Escape');

    await expect(dialog).toHaveCount(0);
    await expect(searchButton).toBeFocused();
  });

  test('404 from search endpoint surfaces unavailable state', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route(
      (url) => url.pathname === '/api/search',
      (route) =>
        route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'not found' }),
        }),
    );

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /Open search/i }).click();

    const input = page.locator('#search-overlay-input');
    await expect(input).toBeFocused();
    await input.fill('missing route');

    await expect(page.locator('.search-overlay__status')).toContainText(/Search is unavailable/i);
    await expect(page.locator('.search-overlay__result-btn')).toHaveCount(0);
  });

  test('Shift+Tab remains trapped inside the overlay', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockSingleSearchResult(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /Open search/i }).click();

    const input = page.locator('#search-overlay-input');
    await expect(input).toBeFocused();
    await input.fill('preview');
    await expect(page.locator('.search-overlay__result-btn').first()).toContainText('mobile preview result');

    await page.keyboard.press('Shift+Tab');
    const focusState = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      return {
        insideOverlay: Boolean(active?.closest('.search-overlay')),
        className: active?.className ?? '',
      };
    });

    expect(focusState.insideOverlay).toBe(true);
    expect(String(focusState.className)).toContain('search-overlay__preview-btn');
  });

  test('Open routes concept search results to focused ledger rows', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route(
      (url) => url.pathname === '/api/search',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            results: [
              {
                source_table: 'graph_nodes',
                primary_key: 'n2',
                snippet: 'Branding',
                rank: 0.98,
                href: null,
              },
            ],
            next_cursor: null,
          }),
        }),
    );

    await page.goto('/#/concepts');
    await page.getByRole('button', { name: /Open search/i }).click();

    const input = page.locator('#search-overlay-input');
    await expect(input).toBeFocused();
    await input.fill('retry');
    await expect(page.locator('.search-overlay__result-btn').first()).toContainText('Branding');

    await page.locator('.search-overlay__preview-btn').click();

    await expect(page.getByRole('dialog', { name: /Search|搜索/i })).toHaveCount(0);
    await expect(page).toHaveURL(/#\/concepts\?tab=ledger&focus=Branding/);
    await expect(page.getByRole('tab', { name: /ledger|台账/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    const focusedRow = page.locator('.concept-ledger__row--focused');
    await expect(focusedRow).toContainText('Branding');
    await expect(focusedRow.getByRole('link', { name: /View in graph|在图谱中查看/i })).toBeVisible();
  });
});
