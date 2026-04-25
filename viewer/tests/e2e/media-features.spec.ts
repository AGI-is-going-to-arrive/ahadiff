import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('media features', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('print emulation: dashboard heading still visible, no horizontal overflow', async ({
    page,
  }) => {
    await page.emulateMedia({ media: 'print' });
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('forced-colors active: key elements remain in DOM', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('group', { name: /Language|语言/i })).toBeVisible();
    await expect(page.getByRole('navigation')).toBeVisible();
  });

  test('prefers-reduced-motion active: language switch still works', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/运行面板/);
  });

  test('dark color scheme: topbar and sidebar render', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/');

    await expect(page.getByRole('banner')).toBeVisible();
    await expect(page.getByRole('navigation')).toBeVisible();
  });
});
