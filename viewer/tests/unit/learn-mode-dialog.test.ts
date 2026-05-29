import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Locator, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';

const TEST_PATH = '/__learn-mode-dialog-test.html';

const HARNESS_HTML = String.raw`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>LearnModeDialog unit harness</title>
  </head>
  <body>
    <div id="root"></div>
    <script>
      window.__requestLearnCalls = [];
      window.__requestLearnOptions = [];
      window.__onCloseCalls = 0;
      window.__currentPhase = 'idle';
    </script>
    <script type="module">
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import LearnModeDialog from '/src/components/LearnModeDialog.tsx';
      import { useLearnStore } from '/src/state/learn-store.ts';
      import { useLocaleStore } from '/src/state/locale-store.ts';

      let root;

      // Stable spy reference (so React selector returns same identity across renders)
      const requestLearnSpy = (payload, options) => {
        window.__requestLearnCalls.push(payload);
        window.__requestLearnOptions.push({
          hasSignal: Boolean(options?.signal),
          aborted: Boolean(options?.signal?.aborted),
        });
        return Promise.resolve();
      };

      window.__renderLearnModeDialog = ({ open = true, locale = 'en', phase = 'idle' } = {}) => {
        window.__requestLearnCalls = [];
        window.__requestLearnOptions = [];
        window.__onCloseCalls = 0;
        window.__currentPhase = phase;

        // Override store with deterministic spy + chosen phase
        useLearnStore.setState({
          phase,
          taskId: null,
          task: null,
          estimate: null,
          error: null,
          errorCode: null,
          lastPayload: null,
          pendingPayload: null,
          retryable: true,
          requestLearn: requestLearnSpy,
        });
        useLocaleStore.setState({ locale });
        document.documentElement.lang = locale;

        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();
        root = createRoot(container);

        const onClose = () => { window.__onCloseCalls += 1; };
        root.render(React.createElement(LearnModeDialog, { open, onClose }));
      };

      window.__updateOpen = (open) => {
        const container = document.getElementById('root');
        if (!root) return;
        const onClose = () => { window.__onCloseCalls += 1; };
        root.render(React.createElement(LearnModeDialog, { open, onClose }));
      };

      window.__cleanupLearnModeDialog = () => {
        root?.unmount();
        root = undefined;
      };

      window.__learnModeDialogReady = true;
    </script>
  </body>
</html>`;

interface RenderOptions {
  open?: boolean;
  locale?: 'en' | 'zh-CN';
  phase?: 'idle' | 'submitting' | 'running' | 'completed' | 'failed';
}

declare global {
  interface Window {
    __cleanupLearnModeDialog: () => void;
    __currentPhase: string;
    __learnModeDialogReady?: boolean;
    __onCloseCalls: number;
    __renderLearnModeDialog: (options?: RenderOptions) => void;
    __requestLearnCalls: Array<Record<string, unknown> | undefined>;
    __requestLearnOptions: Array<{ hasSignal: boolean; aborted: boolean }>;
    __updateOpen: (open: boolean) => void;
  }
}

let server: ViteDevServer;
let browser: Browser;
let page: Page;
let baseUrl = '';

async function createHarnessServer(): Promise<{ server: ViteDevServer; baseUrl: string }> {
  const server = await createServer({
    appType: 'custom',
    clearScreen: false,
    logLevel: 'silent',
    root: process.cwd(),
    server: {
      host: '127.0.0.1',
      port: 0,
    },
  });
  server.middlewares.use(TEST_PATH, async (_req, res) => {
    const html = await server.transformIndexHtml(TEST_PATH, HARNESS_HTML);
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.end(html);
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === 'string') {
    throw new Error('Unable to resolve Vite harness address');
  }
  return { server, baseUrl: `http://127.0.0.1:${address.port}` };
}

async function renderDialog(page: Page, options: RenderOptions = {}): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__learnModeDialogReady));
  await page.evaluate((opts) => window.__renderLearnModeDialog(opts), options);
}

async function getPayloads(page: Page): Promise<Array<Record<string, unknown> | undefined>> {
  return page.evaluate(() => window.__requestLearnCalls);
}

async function getRequestOptions(page: Page): Promise<Array<{ hasSignal: boolean; aborted: boolean }>> {
  return page.evaluate(() => window.__requestLearnOptions);
}

async function getCloseCount(page: Page): Promise<number> {
  return page.evaluate(() => window.__onCloseCalls);
}

function advancedCard(page: Page, radioId: string): Locator {
  return page.locator('.learn-dialog__adv-card').filter({ has: page.locator(`#${radioId}`) });
}

describe('LearnModeDialog', () => {
  beforeAll(async () => {
    const harness = await createHarnessServer();
    server = harness.server;
    baseUrl = harness.baseUrl;
    browser = await chromium.launch();
  }, 60_000);

  beforeEach(async () => {
    page = await browser.newPage({ locale: 'en-US' });
  });

  afterEach(async () => {
    await page.close();
  });

  afterAll(async () => {
    if (browser) await browser.close();
    if (server) await server.close();
  });

  it('renders when open=true and does not render when open=false', async () => {
    // open=false → no dialog in DOM
    await renderDialog(page, { open: false });
    await expect.poll(() => page.locator('[role="dialog"]').count()).toBe(0);

    // Re-render with open=true → dialog appears
    await page.evaluate(() => window.__updateOpen(true));
    await expect.poll(() => page.locator('[role="dialog"]').count()).toBe(1);

    // Toggle back to open=false → dialog removed
    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.locator('[role="dialog"]').count()).toBe(0);
  });

  it('default mode is "working" with the working tile selected', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const tiles = page.locator('.learn-dialog__tile');
    await expect.poll(() => tiles.count()).toBe(4);

    // Working tile (index 0) should have --selected class and checked radio
    const cls = await tiles.nth(0).getAttribute('class');
    expect(cls).toContain('learn-dialog__tile--selected');

    const radio0 = tiles.nth(0).locator('input[type="radio"]');
    await expect(radio0.evaluate((el: HTMLInputElement) => el.checked)).resolves.toBe(true);
    const radio1 = tiles.nth(1).locator('input[type="radio"]');
    await expect(radio1.evaluate((el: HTMLInputElement) => el.checked)).resolves.toBe(false);
    const radio2 = tiles.nth(2).locator('input[type="radio"]');
    await expect(radio2.evaluate((el: HTMLInputElement) => el.checked)).resolves.toBe(false);
    const radio3 = tiles.nth(3).locator('input[type="radio"]');
    await expect(radio3.evaluate((el: HTMLInputElement) => el.checked)).resolves.toBe(false);
  });

  it('clicking "Unstaged changes" tile changes selection', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const tiles = page.locator('.learn-dialog__tile');
    await tiles.nth(1).click();

    await expect.poll(() => tiles.nth(1).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(true);
    await expect.poll(() => tiles.nth(0).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(false);
    const cls = await tiles.nth(1).getAttribute('class');
    expect(cls).toContain('learn-dialog__tile--selected');
  });

  it('clicking "Staged changes" tile changes selection', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const tiles = page.locator('.learn-dialog__tile');
    await tiles.nth(2).click();

    await expect.poll(() => tiles.nth(2).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(true);
    await expect.poll(() => tiles.nth(0).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(false);
    const cls = await tiles.nth(2).getAttribute('class');
    expect(cls).toContain('learn-dialog__tile--selected');
  });

  it('clicking "Last commit" tile changes selection', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const tiles = page.locator('.learn-dialog__tile');
    await tiles.nth(3).click();

    await expect.poll(() => tiles.nth(3).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(true);
    await expect.poll(() => tiles.nth(0).locator('input[type="radio"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(false);
    const cls = await tiles.nth(3).getAttribute('class');
    expect(cls).toContain('learn-dialog__tile--selected');
  });

  it('"More options" toggle expands advanced section (aria-expanded)', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const toggle = page.locator('.learn-dialog__advanced-toggle');
    await expect(toggle.getAttribute('aria-expanded')).resolves.toBe('false');
    await expect.poll(() => page.locator('#learn-dialog-advanced').count()).toBe(0);

    await toggle.click();
    await expect.poll(() => toggle.getAttribute('aria-expanded')).toBe('true');
    await expect.poll(() => page.locator('#learn-dialog-advanced').count()).toBe(1);

    // Click again → collapses
    await toggle.click();
    await expect.poll(() => toggle.getAttribute('aria-expanded')).toBe('false');
    await expect.poll(() => page.locator('#learn-dialog-advanced').count()).toBe(0);
  });

  it('advanced section explains path scope and uncommon sources', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await expect.poll(() => page.locator('#learn-mode-path-scope-hint').textContent()).toContain(
      'Leave empty for all paths',
    );
    await expect.poll(() => page.locator('.learn-dialog__adv-group-title').first().textContent()).toContain(
      'Git Advanced',
    );
    await expect.poll(() => advancedCard(page, 'learn-mode-since').textContent()).toContain(
      'Since date',
    );
    await expect.poll(() => advancedCard(page, 'learn-mode-patch').textContent()).toContain(
      'Paste patch',
    );
    await expect.poll(() => page.locator('#learn-mode-path-scope').getAttribute('aria-describedby')).toBe(
      'learn-mode-path-scope-hint',
    );
  });

  it('inerts all body siblings while open and restores existing inert state', async () => {
    await page.goto(`${baseUrl}${TEST_PATH}`);
    await page.waitForFunction(() => Boolean(window.__learnModeDialogReady));
    await page.evaluate(() => {
      const outside = document.createElement('div');
      outside.id = 'outside-panel';
      document.body.appendChild(outside);
      const alreadyInert = document.createElement('div');
      alreadyInert.id = 'already-inert-panel';
      alreadyInert.setAttribute('inert', '');
      document.body.appendChild(alreadyInert);
      window.__renderLearnModeDialog({ open: true });
    });

    await expect.poll(() => page.locator('.learn-dialog__overlay').count()).toBe(1);
    await expect.poll(() => page.locator('#root').getAttribute('inert')).toBe('');
    await expect.poll(() => page.locator('#outside-panel').getAttribute('inert')).toBe('');
    await expect.poll(() => page.locator('#already-inert-panel').getAttribute('inert')).toBe('');
    await expect.poll(() => page.locator('.learn-dialog__overlay').getAttribute('inert')).toBeNull();
    await expect.poll(() => page.locator('.learn-dialog__overlay').getAttribute('role')).toBeNull();
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');

    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.locator('#root').getAttribute('inert')).toBeNull();
    await expect.poll(() => page.locator('#outside-panel').getAttribute('inert')).toBeNull();
    await expect.poll(() => page.locator('#already-inert-panel').getAttribute('inert')).toBe('');
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
  });

  it('selecting or focusing "Since" input selects that source and deselects quick tiles', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    // Open advanced
    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-since').click();
    await page.waitForSelector('#learn-mode-since-value');
    const sinceInput = page.locator('#learn-mode-since-value');

    // Input is directly focusable; focusing or typing also selects this source.
    await expect.poll(() => sinceInput.isDisabled()).toBe(false);
    await sinceInput.focus();
    await expect.poll(() => page.locator('#learn-mode-since').isChecked()).toBe(true);

    // Quick tiles should all be deselected
    const tiles = page.locator('.learn-dialog__tile');
    await expect.poll(() => tiles.nth(0).evaluate((el) => el.classList.contains('learn-dialog__tile--selected'))).toBe(false);
  }, 10_000);

  it('author filter is exposed as a textbox, not a nested fake button', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-revision').click();
    await expect.poll(() => page.locator('#learn-mode-revision').isChecked()).toBe(true);
    await advancedCard(page, 'learn-mode-since').click();
    await page.waitForSelector('#learn-mode-author');

    const authorRow = page.locator('.learn-dialog__author-row');
    await expect.poll(() => authorRow.getAttribute('role')).toBeNull();
    await expect.poll(() => authorRow.getAttribute('tabindex')).toBeNull();

    const authorInput = page.locator('#learn-mode-author');
    await authorInput.focus();
    await expect.poll(() => page.locator('#learn-mode-since').isChecked()).toBe(true);
    await expect.poll(() => authorInput.evaluate((el) => document.activeElement === el)).toBe(true);
  });

  it('Start button calls requestLearn with staged + unstaged + include_untracked for working mode', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    // Default = working mode
    const startBtn = page.locator('.learn-dialog__btn--primary');
    await startBtn.click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { staged: true, unstaged: true, include_untracked: true, lang: 'en' },
    ]);
    await expect.poll(() => getRequestOptions(page)).toEqual([{ hasSignal: true, aborted: false }]);
    await expect.poll(() => getCloseCount(page)).toBe(1);
  });

  it('defaults learn output language to the active viewer locale', async () => {
    await renderDialog(page, { locale: 'zh-CN' });
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await expect.poll(() => page.locator('#learn-opt-lang').inputValue()).toBe('zh-CN');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { staged: true, unstaged: true, include_untracked: true, lang: 'zh-CN' },
    ]);
  });

  it('sends explicit auto language when Auto is selected', async () => {
    await renderDialog(page, { locale: 'zh-CN' });
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await page.locator('#learn-opt-lang').selectOption('auto');
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { staged: true, unstaged: true, include_untracked: true, lang: 'auto' },
    ]);
  });

  it('path scope input sends deduped changed_paths for working mode', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await page.locator('#learn-mode-path-scope').fill('  src/app.py\n\nsrc/app.py\nviewer\\src\\App.tsx  ');
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      {
        staged: true,
        unstaged: true,
        include_untracked: true,
        changed_paths: ['src/app.py', 'viewer/src/App.tsx'],
        lang: 'en',
      },
    ]);
  });

  it('path scope rejects absolute paths, traversal, and control characters', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    const input = page.locator('#learn-mode-path-scope');
    const startBtn = page.locator('.learn-dialog__btn--primary');

    for (const value of [
      '../secret.txt',
      '/etc/passwd',
      'C:\\temp\\secret.txt',
      'C:secret.txt',
      'src/\u0001bad.py',
      '.git/config',
      '.ahadiff/runs/run-1',
    ]) {
      await input.fill(value);
      await expect.poll(() => startBtn.isDisabled()).toBe(true);
      await expect.poll(() => page.locator('#learn-mode-path-scope-error').textContent()).toContain(
        'repository-relative',
      );
    }
  });

  it('path scope is ignored when last commit mode is submitted', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await page.locator('#learn-mode-path-scope').fill('src/app.py');
    await page.locator('.learn-dialog__tile').nth(3).click();

    await expect.poll(() => page.locator('#learn-mode-path-scope').isDisabled()).toBe(true);
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([{ last: true, lang: 'en' }]);
  });

  it('path scope is ignored for advanced non-worktree modes', async () => {
    const cases = [
      {
        radioId: 'learn-mode-revision',
        fill: async () => page.locator('#learn-mode-revision-value').fill('HEAD~1..HEAD'),
        expected: { revision: 'HEAD~1..HEAD', lang: 'en' },
      },
      {
        radioId: 'learn-mode-patch-url',
        fill: async () => page.locator('#learn-mode-patch-url-value').fill('https://example.test/a.patch'),
        expected: { patch_url: 'https://example.test/a.patch', lang: 'en' },
      },
      {
        radioId: 'learn-mode-compare',
        fill: async () => {
          await page.locator('#learn-mode-compare-a').fill('old.py');
          await page.locator('#learn-mode-compare-b').fill('new.py');
        },
        expected: { compare: ['old.py', 'new.py'], lang: 'en' },
      },
    ] as const;

    for (const item of cases) {
      await renderDialog(page);
      await page.waitForSelector('[role="dialog"]');
      await page.locator('.learn-dialog__advanced-toggle').click();
      await page.waitForSelector('#learn-dialog-advanced');
      await page.locator('#learn-mode-path-scope').fill('src/app.py');
      await advancedCard(page, item.radioId).click();
      await item.fill();
      await page.locator('.learn-dialog__btn--primary').click();
      await expect.poll(() => getPayloads(page)).toEqual([item.expected]);
    }
  });

  it('path scope rejects more than 500 unique paths', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await page.locator('#learn-mode-path-scope').fill(
      Array.from({ length: 501 }, (_value, index) => `src/file-${index}.py`).join('\n'),
    );

    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await expect.poll(() => page.locator('#learn-mode-path-scope-error').textContent()).toContain(
      '500',
    );
  });

  it('Start button calls requestLearn with { unstaged, include_untracked } for unstaged mode', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__tile').nth(1).click();
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { unstaged: true, include_untracked: true, lang: 'en' },
    ]);
    await expect.poll(() => getCloseCount(page)).toBe(1);
  });

  it('Start button calls requestLearn with { staged: true } for staged mode', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__tile').nth(2).click();
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([{ staged: true, lang: 'en' }]);
    await expect.poll(() => getCloseCount(page)).toBe(1);
  });

  it('Start button calls requestLearn with { last: true } for last commit mode', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__tile').nth(3).click();
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([{ last: true, lang: 'en' }]);
    await expect.poll(() => getCloseCount(page)).toBe(1);
  });

  it('Start button is disabled when advanced "since" mode selected with empty input', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    // Open advanced
    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-since').click();

    // Wait until the input is rendered and enabled
    await page.waitForSelector('#learn-mode-since-value');
    const sinceInput = page.locator('#learn-mode-since-value');
    await expect.poll(() => sinceInput.isDisabled()).toBe(false);

    // Button must be disabled (empty since input)
    const startBtn = page.locator('.learn-dialog__btn--primary');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);

    // Now type something → button becomes enabled
    await sinceInput.fill('2 hours ago');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);

    // Clearing back to whitespace-only → disabled again
    await sinceInput.fill('   ');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);
  }, 15_000);

  it('since mode rejects leading dash and control characters in git filters', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-since').click();
    await page.waitForSelector('#learn-mode-since-value');

    const sinceInput = page.locator('#learn-mode-since-value');
    const authorInput = page.locator('#learn-mode-author');
    const startBtn = page.locator('.learn-dialog__btn--primary');

    await sinceInput.fill('--all');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await expect.poll(() => page.locator('#learn-mode-since-error').textContent()).toContain(
      'must not start',
    );

    await sinceInput.fill('2 hours ago');
    await authorInput.fill('bad\u0001author');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await expect.poll(() => page.locator('#learn-mode-author-error').textContent()).toContain(
      'control characters',
    );

    await authorInput.fill('alice');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });

  it('Esc key closes the dialog (calls onClose)', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    expect(await getCloseCount(page)).toBe(0);

    await page.keyboard.press('Escape');

    await expect.poll(() => getCloseCount(page)).toBeGreaterThanOrEqual(1);
  });

  it('force_learn checkbox adds force_learn: true to payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    // Open advanced section so we can reach the checkbox
    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    // Check "force_learn" (first checkbox in options)
    const forceCheckbox = page.locator('.learn-dialog__checkbox input[type="checkbox"]').nth(0);
    await forceCheckbox.check();
    await expect.poll(() => forceCheckbox.evaluate((el: HTMLInputElement) => el.checked)).toBe(
      true,
    );

    // Default mode is still "working" → submit
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { staged: true, unstaged: true, include_untracked: true, force_learn: true, lang: 'en' },
    ]);
  });

  it('compare mode sends compare tuple payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-compare').click();
    await page.waitForSelector('#learn-mode-compare-a');

    await page.locator('#learn-mode-compare-a').fill('main');
    await page.locator('#learn-mode-compare-b').fill('feature-branch');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { compare: ['main', 'feature-branch'], lang: 'en' },
    ]);
  });

  it('compare_dir mode sends compare_dir tuple payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-compare-dir').click();
    await page.waitForSelector('#learn-mode-compare-dir-a');

    await page.locator('#learn-mode-compare-dir-a').fill('/old/dir');
    await page.locator('#learn-mode-compare-dir-b').fill('/new/dir');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { compare_dir: ['/old/dir', '/new/dir'], lang: 'en' },
    ]);
  });

  it('revision mode sends trimmed revision payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-revision').click();
    await page.waitForSelector('#learn-mode-revision-value');
    await page.locator('#learn-mode-revision-value').fill('  abc123  ');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { revision: 'abc123', lang: 'en' },
    ]);
  });

  it('revision mode rejects leading dash and spaces, and caps length', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-revision').click();
    await page.waitForSelector('#learn-mode-revision-value');
    const input = page.locator('#learn-mode-revision-value');
    const startBtn = page.locator('.learn-dialog__btn--primary');
    await expect.poll(() => input.getAttribute('maxLength')).toBe('255');

    for (const value of ['--all', 'bad ref']) {
      await input.fill(value);
      await expect.poll(() => startBtn.isDisabled()).toBe(true);
      await expect.poll(() => page.locator('#learn-mode-revision-error').textContent()).toContain(
        'git revision',
      );
    }

    await input.fill('a'.repeat(255));
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });

  it('typing an inactive advanced source input selects that source', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-revision').click();
    await page.waitForSelector('#learn-mode-revision-value');
    await page.locator('#learn-mode-revision-value').fill('  def456  ');

    await expect.poll(() => page.locator('#learn-mode-revision').isChecked()).toBe(true);
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { revision: 'def456', lang: 'en' },
    ]);
  });

  it('advanced collapse preserves selected advanced mode and payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    const toggle = page.locator('.learn-dialog__advanced-toggle');
    await toggle.click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-revision').click();
    await page.waitForSelector('#learn-mode-revision-value');
    await page.locator('#learn-mode-revision-value').fill('  def456  ');

    await toggle.click();
    await expect.poll(() => page.locator('#learn-dialog-advanced').count()).toBe(0);
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { revision: 'def456', lang: 'en' },
    ]);
  });

  it('patch_url mode sends trimmed patch_url payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-patch-url').click();
    await page.waitForSelector('#learn-mode-patch-url-value');
    await page.locator('#learn-mode-patch-url-value').fill('  https://example.test/file.patch  ');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { patch_url: 'https://example.test/file.patch', lang: 'en' },
    ]);
  });

  it('patch_url mode rejects non-http URLs and embedded credentials', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-patch-url').click();
    await page.waitForSelector('#learn-mode-patch-url-value');
    const input = page.locator('#learn-mode-patch-url-value');
    const startBtn = page.locator('.learn-dialog__btn--primary');

    for (const value of ['javascript:alert(1)', 'file:///tmp/file.patch', 'data:text/plain,patch', 'https://user:pass@example.test/a.patch']) {
      await input.fill(value);
      await expect.poll(() => startBtn.isDisabled()).toBe(true);
      await expect.poll(() => page.locator('#learn-mode-patch-url-error').textContent()).toContain(
        'http or https',
      );
    }

    await input.fill('http://example.test/file.patch');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });

  it('patch mode sends inline patch text', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-patch').click();
    await page.waitForSelector('.learn-dialog__textarea');

    const textarea = page.locator('.learn-dialog__textarea');
    await textarea.fill('--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { patch: '--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new', lang: 'en' },
    ]);
  });

  it('patch mode requires non-empty text and rejects oversized patch text', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-patch').click();
    await page.waitForSelector('.learn-dialog__textarea');

    const startBtn = page.locator('.learn-dialog__btn--primary');
    const textarea = page.locator('.learn-dialog__textarea');

    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await textarea.fill('   ');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);

    await textarea.fill('-');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await expect.poll(() => page.locator('#learn-mode-patch-error').textContent()).toContain(
      'Paste the diff text',
    );

    await textarea.fill('x'.repeat(4097));
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
    await expect.poll(() => textarea.getAttribute('aria-invalid')).toBeNull();

    await textarea.fill('x'.repeat(65537));
    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await expect.poll(() => textarea.getAttribute('aria-invalid')).toBe('true');
    await expect.poll(() => page.locator('#learn-mode-patch-error').textContent()).toContain(
      '65536 bytes',
    );

    await textarea.fill('--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });

  it('since mode with author filter sends author in payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-since').click();
    await page.waitForSelector('#learn-mode-since-value');

    // Fill since input
    await page.locator('#learn-mode-since-value').fill('2 hours ago');

    // Fill author input
    const authorInput = page.locator('#learn-mode-author');
    await authorInput.fill('alice');

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { since: '2 hours ago', author: 'alice', lang: 'en' },
    ]);
  });

  it('does not send author when a non-since mode is submitted', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-since').click();
    await page.waitForSelector('#learn-mode-since-value');
    await page.locator('#learn-mode-since-value').fill('yesterday');
    await page.locator('#learn-mode-author').fill('alice');

    await advancedCard(page, 'learn-mode-revision').click();
    await page.waitForSelector('#learn-mode-revision-value');
    await page.locator('#learn-mode-revision-value').fill('abc123');
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { revision: 'abc123', lang: 'en' },
    ]);
  });

  it('dry_run checkbox adds dry_run: true to payload', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    // dry_run is the 3rd checkbox (after force_learn and use_graphify)
    const dryRunCheckbox = page.locator('.learn-dialog__checkbox input[type="checkbox"]').nth(2);
    await dryRunCheckbox.check();

    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      { staged: true, unstaged: true, include_untracked: true, dry_run: true, lang: 'en' },
    ]);
  });

  it('advanced run options explain backend behavior', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await expect.poll(() => page.locator('.learn-dialog__options-title').textContent()).toBe(
      'Run options',
    );
    await expect.poll(() => page.locator('.learn-dialog__checkbox-hint').nth(0).textContent())
      .toContain('Backend still captures and checks safety');
    await expect.poll(() => page.locator('.learn-dialog__checkbox-hint').nth(1).textContent())
      .toContain('Graphify code-map context');
    await expect.poll(() => page.locator('.learn-dialog__checkbox-hint').nth(2).textContent())
      .toContain('No lesson or quiz is generated');
  });

  it('lang and privacy controls are included in payload when explicitly selected', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await page.locator('#learn-opt-lang').selectOption('zh-CN');
    await page.locator('#learn-opt-privacy').selectOption('redacted_remote');
    await page.locator('.learn-dialog__btn--primary').click();

    await expect.poll(() => getPayloads(page)).toEqual([
      {
        staged: true,
        unstaged: true,
        include_untracked: true,
        lang: 'zh-CN',
        privacy_mode: 'redacted_remote',
      },
    ]);
  });

  it('compare mode button disabled when one input is empty', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');

    await advancedCard(page, 'learn-mode-compare').click();
    await page.waitForSelector('#learn-mode-compare-a');

    // Only fill one input
    await page.locator('#learn-mode-compare-a').fill('main');

    // Button should be disabled (second input empty)
    const startBtn = page.locator('.learn-dialog__btn--primary');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);

    // Fill second → enabled
    await page.locator('#learn-mode-compare-b').fill('develop');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });

  it('compare mode rejects double-empty and whitespace-only refs', async () => {
    await renderDialog(page);
    await page.waitForSelector('[role="dialog"]');

    await page.locator('.learn-dialog__advanced-toggle').click();
    await page.waitForSelector('#learn-dialog-advanced');
    await advancedCard(page, 'learn-mode-compare').click();
    await page.waitForSelector('#learn-mode-compare-a');

    const startBtn = page.locator('.learn-dialog__btn--primary');
    const inputA = page.locator('#learn-mode-compare-a');
    const inputB = page.locator('#learn-mode-compare-b');

    await expect.poll(() => startBtn.isDisabled()).toBe(true);
    await inputA.fill('   ');
    await inputB.fill('\t  ');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);

    await inputA.fill('main');
    await expect.poll(() => startBtn.isDisabled()).toBe(true);

    await inputB.fill('feature');
    await expect.poll(() => startBtn.isDisabled()).toBe(false);
  });
});
