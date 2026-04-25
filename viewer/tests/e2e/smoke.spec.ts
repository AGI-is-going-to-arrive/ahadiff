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
});
