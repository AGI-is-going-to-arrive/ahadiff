import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('i18n', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await installServeMock(page);
  });

  test('language switcher toggles Dashboard heading between en and zh-CN', async ({ page }) => {
    await page.goto('/');

    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
    await expect(heading).toHaveText(/Dashboard/i);

    const switcher = page.getByRole('group', { name: /Language|语言/i });
    await expect(switcher).toBeVisible();

    const zhBtn = switcher.getByRole('button', { name: '简体中文' });
    await zhBtn.click();

    await expect(zhBtn).toHaveAttribute('aria-pressed', 'true');
    await expect(heading).toHaveText(/运行面板/);
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');

    const enBtn = switcher.getByRole('button', { name: 'English' });
    await enBtn.click();

    await expect(enBtn).toHaveAttribute('aria-pressed', 'true');
    await expect(heading).toHaveText(/Dashboard/i);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  });

  test('locale persists across reloads via cookie', async ({ page, context }) => {
    await page.goto('/');
    const putWait = page.waitForResponse(
      (res) => res.url().endsWith('/api/locale') && res.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    // Block on PUT /api/locale so the mock-side addCookies completes before reload.
    await putWait;

    // Belt-and-suspenders: WebKit + Playwright sometimes drops document.cookie
    // writes across reload. Mirror what the real backend's Set-Cookie would do
    // by syncing the cookie into the BrowserContext explicitly.
    await context.addCookies([
      {
        name: 'ahadiff_lang',
        value: 'zh-CN',
        url: 'http://localhost:5173/',
        sameSite: 'Lax',
      },
    ]);

    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/运行面板/);
  });

  test('sidebar nav_label switches with locale', async ({ page }) => {
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: /Navigation|导航/ });
    await expect(nav).toBeVisible();

    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(page.getByRole('navigation', { name: '导航' })).toBeVisible();
  });

  test('Diff route renders localized heading in zh-CN', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '简体中文' }).click();
    await page.goto('/#/run/test-run/diff');

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/差异/);
  });

  test('DiffView does not re-parse diff content across locale switch', async ({ page }) => {
    await page.goto('/#/run/test-run/diff');
    const region = page.getByRole('region', { name: /Diff|差异/ });
    await expect(region).toBeVisible();

    // Stash a reference to the current DOM node and its parsed line count on window
    await page.evaluate(() => {
      const el = document.querySelector<HTMLElement>('.diff-view');
      const w = window as unknown as {
        __diffRegion?: HTMLElement | null;
        __diffLineCount?: number;
      };
      w.__diffRegion = el;
      w.__diffLineCount = el ? el.querySelectorAll('.diff-line').length : 0;
    });

    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(page.getByRole('region', { name: '差异' })).toBeVisible();

    const result = await page.evaluate(() => {
      const el = document.querySelector<HTMLElement>('.diff-view');
      const w = window as unknown as {
        __diffRegion?: HTMLElement | null;
        __diffLineCount?: number;
      };
      return {
        sameNode: el === w.__diffRegion,
        sameCount: el ? el.querySelectorAll('.diff-line').length === w.__diffLineCount : false,
        lineCount: el ? el.querySelectorAll('.diff-line').length : 0,
      };
    });

    // React.memo + stable props keep the same DOM node and parsed-line count
    expect(result.sameNode).toBe(true);
    expect(result.sameCount).toBe(true);
    expect(result.lineCount).toBeGreaterThan(0);
  });
});
