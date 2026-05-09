import { test, expect } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('Improve Preview tab on Ratchet page', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('shows improve preview tab in ratchet page', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await expect(improveTab).toBeVisible();
    await improveTab.click();
    await expect(improveTab).toHaveAttribute('aria-selected', 'true');
  });

  test('shows read-only banner', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    const banner = page.locator('.improve-preview__banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/read-only|只读/i);
  });

  test('displays anchor and baseline run info', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    await page.locator('.improve-preview__banner').waitFor({ state: 'visible' });

    const dlRows = page.locator('.improve-preview__dl-row');
    await expect(dlRows.first()).toBeVisible();
    expect(await dlRows.count()).toBeGreaterThanOrEqual(3);

    const scores = page.locator('.improve-preview__score');
    expect(await scores.count()).toBeGreaterThanOrEqual(1);
  });

  test('shows provider configured badge', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    const providerBadge = page.locator('.improve-preview__provider-badge--ok');
    await expect(providerBadge).toBeVisible();
  });

  test('shows mutable prompts list', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    await page.locator('.improve-preview__banner').waitFor({ state: 'visible' });

    const prompts = page.locator('.improve-preview__prompt-item');
    await expect(prompts.first()).toBeVisible();
    expect(await prompts.count()).toBe(5);
  });

  test('shows existing sessions', async ({ page }) => {
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    await page.locator('.improve-preview__banner').waitFor({ state: 'visible' });

    const sessionCards = page.locator('.improve-preview__session-card');
    await expect(sessionCards.first()).toBeVisible();
    expect(await sessionCards.count()).toBe(1);

    const statusPill = page.locator('.improve-preview__status-pill');
    await expect(statusPill).toContainText('discard');
  });

  test('no write action buttons exist in improve preview', async ({ page }) => {
    const forbiddenWrites: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      const method = request.method();
      if (
        method !== 'GET' &&
        url.pathname !== '/api/auth/token' &&
        /^\/api\/(improve|learn|install|config|providers|signals|review)/.test(url.pathname)
      ) {
        forbiddenWrites.push(`${method} ${url.pathname}`);
      }
    });
    await page.goto('/#/ratchet');

    const improveTab = page.getByRole('tab', { name: /improve|改进/i });
    await improveTab.click();

    const panel = page.locator('#ratchet-panel-improve');
    const actionButtons = panel.locator('button:not([class*="retry"]):not([class*="filter"])');
    const buttonTexts = await actionButtons.allTextContents();
    for (const text of buttonTexts) {
      expect(text.toLowerCase()).not.toMatch(/run|start|trigger|execute|improve now/);
    }
    expect(forbiddenWrites).toEqual([]);
  });
});
