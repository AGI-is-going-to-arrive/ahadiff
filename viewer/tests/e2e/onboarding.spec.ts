import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

/**
 * Helpers
 */

interface RGB {
  r: number;
  g: number;
  b: number;
}

function parseRgb(value: string): RGB | null {
  const match = value.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
  if (!match) return null;
  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
  };
}

function channelDistance(a: RGB, b: RGB): number {
  return Math.max(Math.abs(a.r - b.r), Math.abs(a.g - b.g), Math.abs(a.b - b.b));
}

const ACCENT_RGB: RGB = { r: 190, g: 82, b: 54 };
const SUCCESS_RGB: RGB = { r: 47, g: 111, b: 79 };

async function mockDbCheck(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/db/check',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          healthy: true,
          schema_version: 9,
          quick_check: 'ok',
          event_count: 12,
          card_count: 5,
        }),
      }),
  );
}

test.describe('onboarding (B6 e2e)', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  // 1. Cold-load `/#/onboarding` directly (no prior visit). The first
  //    DiagnosticRow renders icon and text on the same row (y-delta < 6px).
  test('cold-load: first diag-row icon and text are on the same row', async ({ page }) => {
    await mockDbCheck(page);
    await page.goto('/#/onboarding');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const firstRow = page
      .locator('[data-testid="onboarding-diagnostics"] .diag-row')
      .first();
    await expect(firstRow).toBeVisible();
    const icon = firstRow.locator('.diag-row__icon').first();
    const text = firstRow.locator('.diag-row__text').first();
    await expect(icon).toBeVisible();
    await expect(text).toBeVisible();

    const iconBox = await icon.boundingBox();
    const textBox = await text.boundingBox();
    expect(iconBox).not.toBeNull();
    expect(textBox).not.toBeNull();
    if (!iconBox || !textBox) throw new Error('bounding boxes unavailable');
    const iconCenter = iconBox.y + iconBox.height / 2;
    const textCenter = textBox.y + textBox.height / 2;
    expect(Math.abs(iconCenter - textCenter)).toBeLessThan(6);
  });

  // 2. Schema/info row never renders a literal "i" character. The info icon is
  //    a lucide <svg> (visual-only); ensure no plain text node equals "i".
  test('info diag-row uses an SVG icon and never renders literal "i"', async ({ page }) => {
    await mockDbCheck(page);
    await page.goto('/#/onboarding');
    await expect(
      page.locator('[data-testid="onboarding-diagnostics"] .diag-row').first(),
    ).toBeVisible();

    // No plain text node containing only "i" inside the diagnostics block.
    const literalI = page.locator(
      '[data-testid="onboarding-diagnostics"] >> text=/^\\s*i\\s*$/',
    );
    await expect(literalI).toHaveCount(0);

    // At least one info-status row should expose an svg icon (visual cue).
    const infoSvgs = page.locator(
      '[data-testid="onboarding-diagnostics"] .diag-row[data-status="info"] svg',
    );
    expect(await infoSvgs.count()).toBeGreaterThanOrEqual(1);
  });

  // 3. All-pass doctor → completion card visible AND Next CTA hidden.
  test('doctor all-pass shows completion and hides Next CTA', async ({ page }) => {
    await mockDbCheck(page);
    await page.goto('/#/onboarding');

    const completion = page.locator('[data-testid="onboarding-completion"]');
    await expect(completion).toBeVisible({ timeout: 8_000 });

    // When completion renders, the inline step nav (with Next) is replaced by
    // the completion CTA. Next must NOT be visible.
    const nextBtn = page.locator('[data-testid="onboarding-cta-next"]');
    await expect(nextBtn).toBeHidden();

    // Completion CTA is present.
    await expect(page.locator('[data-testid="onboarding-cta-complete"]')).toBeVisible();
  });

  // 4. Completion card border is success-green, NOT accent-orange.
  test('completion card border is success-green, not accent-orange', async ({ page }) => {
    await mockDbCheck(page);
    await page.goto('/#/onboarding');

    const completion = page.locator('[data-testid="onboarding-completion"]');
    await expect(completion).toBeVisible({ timeout: 8_000 });

    const borderColor = await completion.evaluate((el) => {
      const style = window.getComputedStyle(el);
      return style.borderTopColor || style.borderColor;
    });

    const parsed = parseRgb(borderColor);
    expect(parsed, `parse border color: ${borderColor}`).not.toBeNull();
    if (!parsed) throw new Error('border color did not parse');

    // Far from accent (per-channel >20).
    expect(channelDistance(parsed, ACCENT_RGB)).toBeGreaterThan(20);
    // Close to success-green (per-channel <=25).
    expect(channelDistance(parsed, SUCCESS_RGB)).toBeLessThanOrEqual(25);
  });

  // 5. No horizontal overflow across mainstream viewports.
  test('no horizontal overflow at 1280/1024/768/414 widths', async ({ page }) => {
    await mockDbCheck(page);
    const widths = [1280, 1024, 768, 414];
    for (const width of widths) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/#/onboarding');
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(() =>
        document.body.scrollWidth - window.innerWidth,
      );
      expect(overflow, `viewport ${width}px overflow`).toBeLessThanOrEqual(1);
    }
  });

  // 6. Hash-nav chip click scrolls the diagnostics section into the viewport.
  test('nav chip click scrolls diagnostics into viewport', async ({ page }) => {
    await mockDbCheck(page);
    await page.setViewportSize({ width: 1024, height: 800 });
    await page.goto('/#/onboarding');
    await expect(page.locator('[data-testid="onboarding-diagnostics"]')).toBeVisible();

    await page.locator('[data-testid="onboarding-nav-chip-diagnostics"]').click();

    // Allow smooth scroll to settle; reduced motion may finish synchronously.
    await page.waitForTimeout(450);

    const rect = await page
      .locator('[data-testid="onboarding-diagnostics"]')
      .evaluate((el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, height: r.height, vh: window.innerHeight };
      });
    expect(rect.top).toBeGreaterThanOrEqual(-1);
    expect(rect.top).toBeLessThanOrEqual(rect.vh);
  });

  // 7. Sidebar keeps Welcome as the Workspace entry and the System section as
  //    Get Started → Guide → Settings, matching the Warm v6 navigation split.
  test('sidebar Workspace/System order follows Warm v6 navigation split', async ({ page }) => {
    await mockDbCheck(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/#/onboarding');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const workspaceSection = page.locator(
      '.sidebar__section[aria-labelledby="sidebar-section-workspace"]',
    );
    await expect(workspaceSection).toBeVisible();
    await expect(workspaceSection.locator('.sidebar__item').first()).toContainText(/(Welcome|欢迎)/);

    // Locate SYSTEM section by its labeled heading id (Sidebar.tsx).
    const systemSection = page.locator(
      '.sidebar__section[aria-labelledby="sidebar-section-system"]',
    );
    await expect(systemSection).toBeVisible();

    const items = systemSection.locator('.sidebar__item');
    await expect(items).toHaveCount(3);

    const expected: Array<RegExp> = [
      /(Get Started|快速上手)/,
      /(Guide|使用指南)/,
      /(Settings|设置)/,
    ];

    for (let i = 0; i < expected.length; i += 1) {
      const text = await items.nth(i).innerText();
      expect(text, `SYSTEM item #${i + 1}`).toMatch(expected[i]);
    }
  });
});
