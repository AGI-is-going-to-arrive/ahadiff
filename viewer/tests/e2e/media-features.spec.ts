import { expect, test, type Locator, type Page } from '@playwright/test';
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

async function installDashboardRunsMock(page: Page): Promise<void> {
  await page.unroute((url) => url.pathname === '/api/runs');
  await page.route(
    (url) => url.pathname === '/api/runs',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runs: [
            {
              run_id: 'run-graphify-a',
              source_ref: 'HEAD~1',
              source_kind: 'git_ref',
              content_lang: 'en',
              capability_level: 3,
              verdict: 'PASS',
              overall: 91,
              status: 'baseline',
              weakest_dim: 'evidence',
              created_at: '2026-04-28T00:00:00Z',
              degraded_flags: {},
            },
            {
              run_id: 'run-graphify-b',
              source_ref: 'HEAD',
              source_kind: 'git_ref',
              content_lang: 'en',
              capability_level: 3,
              verdict: 'CAUTION',
              overall: 74,
              status: 'baseline',
              weakest_dim: 'conciseness',
              created_at: '2026-04-29T00:00:00Z',
              degraded_flags: {},
            },
          ],
        }),
      }),
  );
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

  test('print emulation: GraphifyCard remains visible and printable', async ({ page }) => {
    await page.emulateMedia({ media: 'print' });
    await installDashboardRunsMock(page);
    await page.goto('/');

    const card = page.locator('.graphify-card--compact');
    await expect(card).toBeVisible();
    await expect(card.getByText('Graphify source')).toBeVisible();
    const colors = await card.evaluate((el) => ({
      background: getComputedStyle(el).backgroundColor,
      border: getComputedStyle(el).borderTopColor,
      leftBorder: getComputedStyle(el).borderLeftWidth,
      radius: getComputedStyle(el).borderTopLeftRadius,
      color: getComputedStyle(el).color,
    }));
    expect(colors.background).not.toBe('rgba(0, 0, 0, 0)');
    expect(colors.border).not.toBe('rgba(0, 0, 0, 0)');
    expect(colors.leftBorder).toBe('3px');
    expect(colors.radius).toBe('8px');
    expect(colors.color).not.toBe('rgba(0, 0, 0, 0)');
  });

  test('print emulation: settings panels remain printable', async ({ page }) => {
    await page.emulateMedia({ media: 'print' });
    await page.goto('/#/settings');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText('Privacy controls')).toBeVisible();
    await expect(page.getByText('Graphify source')).toBeVisible();
    await expect(page.locator('#spanel-audit .settings-card__header h2')).toContainText('Audit Log');
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('print emulation: full GraphifyCard provenance rows remain printable', async ({ page }) => {
    await page.emulateMedia({ media: 'print' });
    await page.goto('/#/settings');

    const card = page.locator('.graphify-card').first();
    await expect(card).toBeVisible();
    await expect(card.locator('.graphify-card__icon')).toBeVisible();
    await expect(card.locator('.graphify-card__title')).toContainText('Graphify source');

    const rows = card.locator('.graphify-card__row');
    const firstRowLabel = rows.first().locator('.graphify-card__row-label');
    await expect(firstRowLabel).toBeVisible();
    await expect(firstRowLabel).toContainText('source:');

    const rowColors = await rows.first().evaluate((el) => ({
      color: getComputedStyle(el).color,
      fontFamily: getComputedStyle(el).fontFamily,
    }));
    expect(rowColors.color).not.toBe('rgba(0, 0, 0, 0)');
    expect(rowColors.fontFamily).toContain('mono');
  });

  test('print emulation: concepts heading and detail panel remain printable', async ({
    page,
  }) => {
    await page.goto('/#/concepts?tab=graph');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.locator('.concept-graph__a11y-node').first().focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.concept-graph__detail')).toBeVisible();
    await page.emulateMedia({ media: 'print' });
    await expect(page.locator('.concept-graph__detail')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('print emulation: lesson navigation sidebars stay hidden', async ({ page }) => {
    await page.emulateMedia({ media: 'print' });
    await page.goto('/#/run/test-run/lesson');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.lesson__prose')).toBeVisible();
    await expect(page.locator('.lesson__toc')).toBeHidden();
    await expect(page.locator('.lesson-sidebar')).toBeHidden();
    // Per blueprint: lesson rail (claims/sources/notes) stays visible in print.
    await expect(page.locator('.lesson__rail')).toBeVisible();
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

  test('forced-colors active: GraphifyCard uses readable system colors', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await installDashboardRunsMock(page);
    await page.goto('/');

    const card = page.locator('.graphify-card--compact');
    const badge = card.locator('.graphify-badge');
    await expect(card).toBeVisible();
    await expect(badge).toBeVisible();

    const values = await badge.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      probe.style.borderColor = 'Highlight';
      document.body.append(probe);
      const cardEl = el.closest('.graphify-card');
      const result = {
        badgeBackground: getComputedStyle(el).backgroundColor,
        badgeBorder: getComputedStyle(el).borderTopColor,
        badgeColor: getComputedStyle(el).color,
        canvas: getComputedStyle(probe).backgroundColor,
        canvasText: getComputedStyle(probe).color,
        cardBackground: cardEl ? getComputedStyle(cardEl).backgroundColor : '',
        cardColor: cardEl ? getComputedStyle(cardEl).color : '',
        highlight: getComputedStyle(probe).borderTopColor,
      };
      probe.remove();
      return result;
    });
    expect(values.cardBackground).toBe(values.canvas);
    expect(values.cardColor).toBe(values.canvasText);
    expect(values.badgeBackground).toBe(values.canvas);
    expect(values.badgeColor).toBe(values.highlight);
    expect(values.badgeBorder).toBe(values.highlight);
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

  test('prefers-reduced-motion active: concepts graph uses stable static layout', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/#/concepts?tab=graph');

    const canvas = page.locator('.concept-graph__canvas canvas');
    await expect(canvas).toBeVisible();
    await expect(page.locator('.concept-graph__a11y-node')).toHaveCount(3);
    const before = await canvas.boundingBox();
    await page.waitForTimeout(250);
    const after = await canvas.boundingBox();
    expect(after).toEqual(before);
  });

  test('forced-colors active: concepts badges and filters use system colors', async ({
    page,
  }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/#/concepts?tab=graph');

    await page.locator('.concept-graph__a11y-node').first().focus();
    await page.keyboard.press('Enter');
    const badge = page.locator('.concept-graph__kind-badge').first();
    await expect(badge).toBeVisible();
    const values = await badge.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      document.body.append(probe);
      const graphCanvas = document.querySelector('.concept-graph__canvas');
      const result = {
        badgeColor: getComputedStyle(el).color,
        canvasText: getComputedStyle(probe).color,
        badgeBackground: getComputedStyle(el).backgroundColor,
        canvasBackground: getComputedStyle(probe).backgroundColor,
        graphBorder: graphCanvas ? getComputedStyle(graphCanvas).borderTopColor : '',
      };
      probe.remove();
      return result;
    });
    expect(values.badgeColor).toBe(values.canvasText);
    expect(values.badgeBackground).toBe(values.canvasBackground);
    expect(values.graphBorder).toBe(values.canvasText);

    const chip = page.locator('.concept-graph__filter-chip[data-kind="module"]');
    await expect(chip).toBeVisible();
    const inactiveChipColors = await chip.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      document.body.append(probe);
      const result = {
        color: getComputedStyle(el).color,
        background: getComputedStyle(el).backgroundColor,
        canvasText: getComputedStyle(probe).color,
        canvas: getComputedStyle(probe).backgroundColor,
      };
      probe.remove();
      return result;
    });
    expect(inactiveChipColors.color).toBe(inactiveChipColors.canvasText);
    expect(inactiveChipColors.background).toBe(inactiveChipColors.canvas);

    await chip.click();
    await expect(chip).toHaveAttribute('aria-pressed', 'true');
    const activeChipColors = await chip.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'Highlight';
      probe.style.backgroundColor = 'Canvas';
      const textProbe = document.createElement('span');
      textProbe.style.color = 'CanvasText';
      document.body.append(probe);
      document.body.append(textProbe);
      const result = {
        color: getComputedStyle(el).color,
        background: getComputedStyle(el).backgroundColor,
        outline: getComputedStyle(el).outlineColor,
        highlight: getComputedStyle(probe).color,
        canvasText: getComputedStyle(textProbe).color,
        canvas: getComputedStyle(probe).backgroundColor,
      };
      probe.remove();
      textProbe.remove();
      return result;
    });
    expect([activeChipColors.highlight, activeChipColors.canvasText]).toContain(
      activeChipColors.color,
    );
    expect(activeChipColors.outline).toBe(activeChipColors.highlight);
    expect(activeChipColors.background).toBe(activeChipColors.canvas);
    await expect(page.getByRole('group', { name: /Filter graph|筛选图谱/i })).toBeVisible();
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

  test('print emulation: landing demo boundary visible', async ({ page }) => {
    await page.goto('/#/welcome');
    await page.waitForSelector('.landing');
    await page.emulateMedia({ media: 'print' });

    const banner = page.locator('.demo-banner').first();
    await expect(banner).toBeVisible();

    const tags = page.locator('.demo-tag');
    await expect(tags.first()).toBeVisible();

    const borderWidth = await banner.evaluate(
      (el) => getComputedStyle(el).borderTopWidth,
    );
    expect(borderWidth).not.toBe('0px');

    const bodyOverflow = await page.evaluate(
      () => document.body.scrollWidth <= document.body.clientWidth,
    );
    expect(bodyOverflow).toBe(true);

    await expect(page.locator('h1, h2').first()).toBeVisible();
  });

  test('forced-colors active: dashboard weak chips visible', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await installDashboardRunsMock(page);
    await page.goto('/');

    const chip = page.locator('.dashboard__weak-chip').first();
    await expect(chip).toBeVisible();
    const values = await chip.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      document.body.append(probe);
      const result = {
        color: getComputedStyle(el).color,
        background: getComputedStyle(el).backgroundColor,
        borderColor: getComputedStyle(el).borderTopColor,
        canvasText: getComputedStyle(probe).color,
        canvas: getComputedStyle(probe).backgroundColor,
      };
      probe.remove();
      return result;
    });
    expect(values.color).toBe(values.canvasText);
    expect(values.background).toBe(values.canvas);
    expect(values.borderColor).toBe(values.canvasText);
  });

  test('forced-colors active: guide accordion summary remains visible', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'forced-colors emulation is Chromium-only');
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/#/guide');

    const summary = page.locator('.guide-accordion__summary').first();
    await expect(summary).toBeVisible();

    // Summary text/icon must remain visible under forced-colors
    const values = await summary.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.color = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      document.body.append(probe);
      const result = {
        color: getComputedStyle(el).color,
        canvasText: getComputedStyle(probe).color,
      };
      probe.remove();
      return result;
    });
    expect(values.color).toBe(values.canvasText);

    // Copy button on a command block should also be visible
    const copyBtn = page.locator('.command-block__copy-btn').first();
    await expect(copyBtn).toBeVisible();
  });

  test('prefers-reduced-motion active: guide accordion chevrons do not transform', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/#/guide');

    const summary = page.locator('.guide-accordion__summary').first();
    const chevron = page.locator('.guide-accordion__chevron').first();
    await expect(summary).toBeVisible();
    await summary.click();

    const transform = await chevron.evaluate((el) => getComputedStyle(el).transform);
    expect(transform).toBe('none');
  });

  test('small viewports: guide command blocks do not create horizontal overflow', async ({
    page,
  }) => {
    for (const width of [320, 360, 375]) {
      await page.setViewportSize({ width, height: 700 });
      await page.goto('/#/guide');
      await expect(page.locator('.guide')).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);

      const firstCardBox = await page.locator('.guide-card').first().boundingBox();
      expect(firstCardBox).not.toBeNull();
      if (firstCardBox) {
        expect(firstCardBox.width).toBeLessThanOrEqual(width);
      }
    }
  });

  test('forced-colors active: quiz mode badge visible', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/#/run/test-run/quiz');

    const badge = page.locator('.quiz-page__mode-badge').first();
    await expect(badge).toBeVisible();
    const values = await badge.evaluate((el) => {
      const cs = getComputedStyle(el);
      return {
        color: cs.color,
        background: cs.backgroundColor,
        borderStyle: cs.borderTopStyle,
        borderWidth: cs.borderTopWidth,
      };
    });
    expect(values.color).not.toBe(values.background);
    expect(values.borderStyle).not.toBe('none');
    expect(parseInt(values.borderWidth, 10)).toBeGreaterThanOrEqual(1);
  });

  test('forced-colors active: review summary visible', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/#/review');

    await expect(page.locator('.review__summary')).toBeVisible();
    const values = await page.locator('.review__summary').evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.borderColor = 'CanvasText';
      document.body.append(probe);
      const result = {
        borderColor: getComputedStyle(el).borderTopColor,
        expected: getComputedStyle(probe).borderTopColor,
      };
      probe.remove();
      return result;
    });
    expect(values.borderColor).toBe(values.expected);
  });

  test('forced-colors active: judge note card visible', async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    await page.goto('/#/ratchet');

    const judgeTab = page.locator('.ratchet-tabs__tab', { hasText: /Judge/i });
    await expect(judgeTab).toBeVisible();
    await judgeTab.click();

    const card = page.locator('.judge-note-card').first();
    await expect(card).toBeVisible();
    const values = await card.evaluate((el) => {
      const probe = document.createElement('span');
      probe.style.borderColor = 'CanvasText';
      probe.style.backgroundColor = 'Canvas';
      document.body.append(probe);
      const result = {
        borderColor: getComputedStyle(el).borderTopColor,
        background: getComputedStyle(el).backgroundColor,
        expectedBorder: getComputedStyle(probe).borderTopColor,
        expectedBg: getComputedStyle(probe).backgroundColor,
      };
      probe.remove();
      return result;
    });
    expect(values.borderColor).toBe(values.expectedBorder);
    expect(values.background).toBe(values.expectedBg);
  });

  test('print emulation: ratchet benchmark rubric grid visible', async ({ page }) => {
    await page.goto('/#/ratchet');

    const benchmarkTab = page.locator('.ratchet-tabs__tab', { hasText: /Benchmark/i });
    await expect(benchmarkTab).toBeVisible();
    await benchmarkTab.click();

    const rubricFirstLabel = page.locator('.rubric-grid__label-text').first();
    await expect(rubricFirstLabel).toBeVisible();

    await page.emulateMedia({ media: 'print' });
    await expect(rubricFirstLabel).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
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
