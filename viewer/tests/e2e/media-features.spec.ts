import { expect, test, type Locator } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

async function expectActiveTransformNone(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const page = locator.page();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  const transform = await locator.evaluate((el) => getComputedStyle(el).transform);
  await page.mouse.up();
  expect(transform).toBe('none');
}

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

  test('print emulation: settings sidebar tabs are hidden', async ({ page }) => {
    await page.emulateMedia({ media: 'print' });
    await page.goto('/#/settings');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.stabs')).toBeHidden();
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
    const menuButton = page.locator('.topbar__mobile-btn');
    if (await menuButton.isVisible()) {
      await menuButton.click();
      await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    }
    await expect(
      page.getByRole('navigation', { name: /Navigation|导航/i }),
    ).toBeVisible();

    const inactiveNewRun = page.locator('.topbar__btn--inactive').filter({ hasText: /New Learn Run/ });
    if (await inactiveNewRun.isVisible()) {
      const colors = await inactiveNewRun.evaluate((el) => {
        const highlightProbe = document.createElement('span');
        highlightProbe.style.backgroundColor = 'Highlight';
        document.body.append(highlightProbe);
        const values = {
          inactiveBg: getComputedStyle(el).backgroundColor,
          highlightBg: getComputedStyle(highlightProbe).backgroundColor,
        };
        highlightProbe.remove();
        return values;
      });
      expect(colors.inactiveBg).not.toBe(colors.highlightBg);
    }
  });

  test('prefers-reduced-motion active: language switch still works', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/运行面板/);
  });

  test('prefers-reduced-motion active: settings tabs and switches do not transition', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/#/settings');

    const tabTransition = await page
      .getByRole('tab', { name: /privacy/i })
      .evaluate((el) => getComputedStyle(el).transitionDuration);
    const switchTransition = await page
      .locator('.settings-toggle')
      .first()
      .evaluate((el) => getComputedStyle(el).transitionDuration);

    expect(tabTransition).toBe('0s');
    expect(switchTransition).toBe('0s');
  });

  test('settings responsive layout has reachable tabs and no horizontal overflow', async ({
    page,
  }) => {
    await page.goto('/#/settings');

    const auditTab = page.getByRole('tab', { name: /audit/i });
    await expect(auditTab).toBeVisible();
    const box = await auditTab.boundingBox();
    expect(box).not.toBeNull();
    if (box) expect(box.height).toBeGreaterThanOrEqual(38);

    await auditTab.click();
    await expect(page.locator('.audit-table')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('prefers-reduced-motion active: lesson controls do not transform', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/#/run/test-run/lesson');

    const tab = page.locator('.scaffolding-tab').first();
    await expect(tab).toBeVisible();
    const box = await tab.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    const transform = await tab.evaluate((el) => getComputedStyle(el).transform);
    await page.mouse.up();

    expect(transform).toBe('none');
  });

  test('prefers-reduced-motion active: shell controls do not transform', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    const menuButton = page.locator('.topbar__mobile-btn');
    if (await menuButton.isVisible()) {
      await expectActiveTransformNone(menuButton);
      await menuButton.click();
      await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    }

    await expectActiveTransformNone(page.getByRole('button', { name: '简体中文' }));
    await expectActiveTransformNone(page.locator('.sidebar__item:not(.sidebar__item--disabled)').first());
  });

  test('dark color scheme: topbar and sidebar render', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/');

    await expect(page.getByRole('banner')).toBeVisible();
    const menuButton = page.locator('.topbar__mobile-btn');
    if (await menuButton.isVisible()) {
      await menuButton.click();
      await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    }
    await expect(
      page.getByRole('navigation', { name: /Navigation|导航/i }),
    ).toBeVisible();
  });
});
