import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';
import { paginatedRunsResponseSchema, providersResponseSchema } from '../../src/api/schemas';

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

  test('no provider keeps setup on step 2, permits free preview and rechecks local configuration', async ({ page }) => {
    let providerAdded = false;
    let providerUnavailable = false;
    let providerReads = 0;
    let modelProbeRequests = 0;
    let learnSubmissions = 0;
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path.includes('/probe')) modelProbeRequests += 1;
      if (request.method() === 'POST' && path === '/api/learn') learnSubmissions += 1;
    });
    await page.route(url => url.pathname === '/api/providers', route => {
      providerReads += 1;
      if (providerUnavailable) return route.fulfill({ status: 500, json: { error: 'private-provider-details', status: 500 } });
      return route.fulfill({ json: providersResponseSchema.parse({ providers: providerAdded ? [{
        alias: 'local', provider_class: 'ollama', provider_kind: 'ollama', model_name: 'local-model',
        base_url: 'http://127.0.0.1:11434', key_status: 'unknown', probed: false,
        probed_max_context: null,
      }] : [] }) });
    });
    await page.goto('/#/onboarding');
    const providerStatus = page.locator('[data-testid="onboarding-provider-status"]');
    await expect(providerStatus).toContainText(/Add a local model or API provider|添加本地模型或 API 提供商/);
    await expect(page.locator('[data-testid="onboarding-step-2"]')).toHaveAttribute('data-state', 'current');
    await expect(page.locator('[data-testid="onboarding-completion"]')).toHaveCount(0);

    await page.locator('[data-testid="onboarding-step-jump-4"]').click();
    await page.locator('[data-learn-source="files"]').click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('#learn-file-before').setInputFiles({ name: 'notes.md', mimeType: 'text/plain', buffer: Buffer.from('old\n') });
    await dialog.locator('#learn-file-after').setInputFiles({ name: 'notes.md', mimeType: 'text/plain', buffer: Buffer.from('new\n') });
    await dialog.locator('.learn-dialog__preview-button').click();
    await expect(dialog.locator('.learn-dialog__preview-diff')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();

    const initialReads = providerReads;
    providerAdded = true;
    await page.locator('[data-testid="onboarding-diag-retry"]').click();
    await expect(providerStatus).toContainText(/does not test the connection or authentication|不测试模型连接或认证/);
    await expect(page.locator('[data-testid="onboarding-step-2"]')).toHaveAttribute('data-state', 'done');
    expect(providerReads).toBeGreaterThan(initialReads);

    providerUnavailable = true;
    await page.locator('[data-testid="onboarding-diag-retry"]').click();
    await expect(providerStatus).toContainText(/Could not read provider configuration|无法读取提供商配置/);
    await expect(providerStatus).not.toContainText('private-provider-details');
    await expect(page.locator('[data-testid="onboarding-step-2"]')).not.toHaveAttribute('data-state', 'done');
    await expect(page.locator('[data-testid="onboarding-completion"]')).toHaveCount(0);
    expect(modelProbeRequests).toBe(0);
    expect(learnSubmissions).toBe(0);
  });

  for (const routeName of ['welcome', 'onboarding', 'guide']) {
    for (const locale of ['en', 'zh-CN']) {
      test(`${routeName} previews selected file contents in ${locale}`, async ({ page, baseURL }) => {
        if (!baseURL) throw new Error('baseURL is required');
        await page.context().addCookies([{ name: 'ahadiff_lang', value: locale, url: baseURL }]);
        const payloads: Array<Record<string, unknown>> = [];
        let submissions = 0;
        page.on('request', request => {
          const path = new URL(request.url()).pathname;
          if (path === '/api/learn/estimate') payloads.push(request.postDataJSON() as Record<string, unknown>);
          if (path === '/api/learn') submissions += 1;
        });
        await page.goto(`/#/${routeName}`);
        const sourceButton = page.locator('[data-learn-source="files"]').first();
        await expect(sourceButton).toContainText(locale === 'en' ? 'Two files' : '两份文件');
        await sourceButton.click();
        const dialog = page.getByRole('dialog');
        await expect(dialog).toBeVisible();
        await page.keyboard.press('ControlOrMeta+K');
        await expect(page.getByRole('dialog')).toHaveCount(1);
        await expect(dialog.locator('.learn-dialog__file-choose').first()).toBeVisible();
        await expect(dialog.locator('#learn-file-before')).toBeHidden();
        await expect(dialog.locator('.learn-dialog__btn--primary')).toBeDisabled();
        await dialog.locator('#learn-file-before').setInputFiles({
          name: '例子.sql', mimeType: 'text/plain', buffer: Buffer.from('SELECT * FROM users;\r\n'),
        });
        await dialog.locator('#learn-file-after').setInputFiles({
          name: '例子.sql', mimeType: 'text/plain', buffer: Buffer.from('SELECT id FROM users;\r\n'),
        });
        await dialog.locator('.learn-dialog__preview-button').click();
        await expect(dialog.locator('.learn-dialog__preview-diff')).toContainText('+after');
        expect(payloads[0]?.compare_files).toEqual([
          { name: '例子.sql', content: 'SELECT * FROM users;\r\n' },
          { name: '例子.sql', content: 'SELECT id FROM users;\r\n' },
        ]);
        expect(payloads[0]?.lang).toBe(locale);
        expect(submissions).toBe(0);
        await expect(dialog.locator('.learn-dialog__btn--primary')).toBeEnabled();

        // Replacing a same-name file must invalidate the previous preview.
        await dialog.locator('#learn-file-after').setInputFiles({
          name: '例子.sql', mimeType: 'text/plain', buffer: Buffer.from('SELECT id, name FROM users;\n'),
        });
        await expect(dialog.locator('.learn-dialog__preview-diff')).toHaveCount(0);
        await expect(dialog.locator('.learn-dialog__btn--primary')).toBeDisabled();
        const overflow = await dialog.evaluate(element => element.scrollWidth - element.clientWidth);
        expect(overflow).toBeLessThanOrEqual(1);

        await page.keyboard.press('Escape');
        await expect(dialog).not.toBeVisible();
        await expect(sourceButton).toBeFocused();
        expect(submissions).toBe(0);
      });
    }
  }

  test('the first completed lesson replaces the empty preview without reloading', async ({ page }) => {
    let completed = false;
    let runListReads = 0;
    const pageErrors: string[] = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    const run = {
      run_id: 'run-first-onboarding', source_ref: 'sha256:synthetic', source_kind: 'file_compare',
      content_lang: 'en', capability_level: 2, verdict: 'PASS', overall: 94.5,
      status: 'non_ratcheted', weakest_dim: 'evidence', created_at: '2026-09-08T00:00:00Z',
      degraded_flags: {},
    };
    await page.route(url => url.pathname === '/api/runs', route => {
      runListReads += 1;
      return route.fulfill({ json: paginatedRunsResponseSchema.parse({ runs: completed ? [run] : [] }) });
    });
    await page.route(url => url.pathname === '/api/learn', route => route.fulfill({ status: 202, json: { task_id: 'task-first-onboarding' } }));
    await page.route(url => url.pathname === '/api/tasks/task-first-onboarding/progress', route => {
      completed = true;
      const task = {
        task_id: 'task-first-onboarding', task_type: 'learn', status: 'completed',
        progress: { current: 10, total: 10, message: 'Done', step_started_at: '2026-09-08T00:00:00Z' },
        result_summary: { run_id: run.run_id, status: 'non_ratcheted', overall: 94.5, verdict: 'PASS', warnings: [] },
        error: null, error_code: null, created_at: '2026-09-08T00:00:00Z', started_at: '2026-09-08T00:00:00Z',
        completed_at: '2026-09-08T00:00:01Z', elapsed_seconds: 1, recovery_hint: null,
      };
      return route.fulfill({
        contentType: 'text/event-stream',
        body: `event: progress\ndata: ${JSON.stringify({ event: 'progress', data: task })}\n\n`,
      });
    });
    await page.goto('/#/onboarding');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('[data-testid="onboarding-preview"]')).toContainText(/No completed run|还没有已完成/);
    await page.locator('[data-learn-source="files"]').click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('#learn-file-before').setInputFiles({ name: 'notes.md', mimeType: 'text/plain', buffer: Buffer.from('old\n') });
    await dialog.locator('#learn-file-after').setInputFiles({ name: 'notes.md', mimeType: 'text/plain', buffer: Buffer.from('new\n') });
    await dialog.locator('.learn-dialog__preview-button').click();
    await expect(dialog.locator('.learn-dialog__preview-diff')).toBeVisible();
    await dialog.locator('.learn-dialog__btn--primary').click();
    await expect(page.locator('.learn-banner')).toHaveClass(/learn-banner--completed/);
    const preview = page.locator('[data-testid="onboarding-preview"]');
    await expect(preview).toContainText(run.run_id);
    await expect(preview.locator('.verdict-badge')).toHaveClass(/verdict-badge--PASS/);
    await expect(preview.locator('.verdict-badge')).toContainText('94.5');
    expect(runListReads).toBeGreaterThanOrEqual(2);
    expect(pageErrors).toEqual([]);
  });

  test('run-list errors are distinct from empty history and a retry bypasses a fresh cached list', async ({ page }) => {
    let rejectList = true;
    let requests = 0;
    const cachedRun = {
      run_id: 'run-before-refresh-error', source_ref: 'sha256:synthetic', source_kind: 'file_compare',
      content_lang: 'en', capability_level: 2, verdict: 'PASS', overall: 91,
      status: 'non_ratcheted', weakest_dim: 'evidence', created_at: '2026-09-08T00:00:00Z',
      degraded_flags: {},
    };
    await page.route(url => url.pathname === '/api/runs', route => {
      requests += 1;
      return rejectList
        ? route.fulfill({ status: 500, json: { error: 'private-server-details', status: 500 } })
        : route.fulfill({ json: paginatedRunsResponseSchema.parse({ runs: [cachedRun] }) });
    });
    await page.goto('/#/onboarding');
    const preview = page.locator('[data-testid="onboarding-preview"]');
    await expect(preview.getByRole('alert')).toContainText(/Could not load learning records|无法加载学习记录/);
    await expect(preview).not.toContainText(/No completed run|还没有已完成/);
    await expect(preview).not.toContainText('private-server-details');
    const firstFailureCount = requests;

    rejectList = false;
    await preview.locator('[data-testid="onboarding-preview-refresh"]').click();
    await expect(preview).toContainText(cachedRun.run_id);
    await expect(preview.getByRole('alert')).toHaveCount(0);
    expect(requests).toBeGreaterThan(firstFailureCount);
    const successfulCount = requests;

    // This request must be sent even though the successful result is younger than the TTL.
    rejectList = true;
    await preview.locator('[data-testid="onboarding-preview-refresh"]').click();
    await expect(preview.getByRole('alert')).toContainText(/Could not refresh learning records|无法刷新学习记录/);
    await expect(preview).toContainText(cachedRun.run_id);
    await expect(preview.locator('.onboarding-preview__meta')).toContainText(/Previously loaded run|此前加载的记录/);
    await expect(preview.getByRole('heading', { level: 2 })).not.toContainText(/latest|最近一次/);
    await expect(preview).not.toContainText(/No completed run|还没有已完成/);
    await expect(preview).not.toContainText('private-server-details');
    expect(requests).toBeGreaterThan(successfulCount);
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
