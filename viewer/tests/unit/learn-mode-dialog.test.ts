import { createHash } from 'node:crypto';
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
      const actualRequestLearn = useLearnStore.getState().requestLearn;
      window.__learnState = () => {
        const { phase, taskId, errorCode, retryable } = useLearnStore.getState();
        return { phase, taskId, errorCode, retryable };
      };

      // Stable spy reference (so React selector returns same identity across renders)
      const requestLearnSpy = (payload, options) => {
        window.__requestLearnCalls.push(payload);
        window.__requestLearnOptions.push({
          hasSignal: Boolean(options?.signal),
          aborted: Boolean(options?.signal?.aborted),
        });
        return Promise.resolve();
      };

      window.__renderLearnModeDialog = ({ open = true, locale = 'en', phase = 'idle', initialSource = 'git', useRealStore = false } = {}) => {
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
          requestLearn: useRealStore ? actualRequestLearn : requestLearnSpy,
        });
        useLocaleStore.setState({ locale });
        document.documentElement.lang = locale;

        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();
        root = createRoot(container);

        const onClose = () => { window.__onCloseCalls += 1; };
        root.render(React.createElement(LearnModeDialog, { open, onClose, initialSource }));
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
  initialSource?: 'git' | 'files' | 'patch' | 'document' | 'snapshot';
  useRealStore?: boolean;
}

declare global {
  interface Window {
    __cleanupLearnModeDialog: () => void;
    __currentPhase: string;
    __learnState: () => { phase: string; taskId: string | null; errorCode: string | null; retryable: boolean };
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

const PREVIEW_PATCH = '--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-before\n+after\n';
let estimatePayloads: Array<Record<string, unknown>> = [];

function makePreview(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    patch_bytes: 74, file_count: 1, total_lines: 5, estimated_tokens: 20,
    provider_context_window: 8192, provider_max_output: null,
    risk_level: 'ok', warnings: [], preview_patch: PREVIEW_PATCH,
    preview_truncated: false, source_kind: 'git_staged_unstaged',
    ...overrides,
  };
}

async function selectSource(source: 'git' | 'files' | 'patch' | 'document' | 'snapshot'): Promise<void> {
  await page.locator(`[data-learn-source="${source}"]`).click();
}

async function openAdvanced(): Promise<void> {
  const toggle = page.locator('.learn-dialog__advanced-toggle');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
}

async function chooseAdvancedMode(id: string): Promise<void> {
  const source = id.includes('patch') ? 'patch' : id.includes('compare') ? 'files' : 'git';
  const sourceButton = page.locator(`[data-learn-source="${source}"]`);
  if (await sourceButton.getAttribute('aria-pressed') !== 'true') await sourceButton.click();
  await openAdvanced();
  await advancedCard(page, id).click();
}

async function previewThenStart(): Promise<void> {
  await page.locator('.learn-dialog__preview-button').click();
  await expect.poll(() => page.locator('.learn-dialog__preview-diff').count()).toBe(1);
  await page.locator('.learn-dialog__btn--primary').click();
}

async function chooseFiles(before: string, after: string, name = 'lesson.py'): Promise<void> {
  await page.locator('#learn-file-before').setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from(before) });
  await page.locator('#learn-file-after').setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from(after) });
  await expect.poll(() => page.locator('.learn-dialog__file-status strong').count()).toBe(2);
}

describe('LearnModeDialog source selection and preview', () => {
  beforeAll(async () => {
    const harness = await createHarnessServer();
    server = harness.server;
    baseUrl = harness.baseUrl;
    browser = await chromium.launch();
  }, 60_000);

  beforeEach(async () => {
    page = await browser.newPage({ locale: 'en-US' });
    estimatePayloads = [];
    await page.route('**/api/auth/token', route => route.fulfill({ json: { token: 'test-write-token' } }));
    await page.route('**/api/learn/estimate', route => {
      estimatePayloads.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: makePreview() });
    });
  });
  afterEach(async () => { await page.close(); });
  afterAll(async () => {
    if (browser) await browser.close();
    if (server) await server.close();
  });

  it('renders five primary sources and keeps Git working-tree capture as the default', async () => {
    await renderDialog(page);
    await expect.poll(() => page.locator('[data-learn-source]').count()).toBe(5);
    await expect.poll(() => page.locator('.learn-dialog__tile').count()).toBe(4);
    await expect.poll(() => page.locator('[data-learn-source="git"]').getAttribute('aria-pressed')).toBe('true');
    await expect.poll(() => page.locator('.learn-dialog__tile').first().locator('input').isChecked()).toBe(true);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    expect(estimatePayloads).toEqual([]);
  });

  it('opens the requested files source directly and exposes accessible file pickers without advanced options', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await expect.poll(() => page.getByLabel('Before', { exact: true }).count()).toBe(1);
    await expect.poll(() => page.getByLabel('After', { exact: true }).count()).toBe(1);
    await expect.poll(() => page.locator('#learn-dialog-advanced').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__explicit-learn input').isChecked()).toBe(true);
    expect(await page.locator('[role="dialog"]').textContent()).toContain('no Git required');
  });

  it.each(['en', 'zh-CN'] as const)('provides a localized keyboard file chooser without a contradictory native empty label in %s', async locale => {
    await renderDialog(page, { initialSource: 'files', locale });
    const chooseBefore = page.getByRole('button', {
      name: locale === 'en' ? 'Choose file: Before' : '修改前：选择文件', exact: true,
    });
    await expect.poll(() => chooseBefore.isVisible()).toBe(true);
    await expect.poll(() => page.getByRole('button', {
      name: locale === 'en' ? 'Choose file: After' : '修改后：选择文件', exact: true,
    }).count()).toBe(1);
    const firstChooser = page.waitForEvent('filechooser');
    await chooseBefore.focus();
    await page.keyboard.press('Enter');
    await (await firstChooser).setFiles({ name: 'same.md', mimeType: 'text/plain', buffer: Buffer.from('original content') });

    const reselect = page.getByRole('button', {
      name: locale === 'en' ? 'Reselect file: Before' : '修改前：重新选择文件', exact: true,
    });
    await expect.poll(() => reselect.isVisible()).toBe(true);
    await expect.poll(() => page.locator('#learn-file-before-status strong').textContent()).toBe('same.md');
    await expect.poll(() => page.locator('#learn-file-before').isVisible()).toBe(false);
    expect(await page.locator('#learn-file-before').inputValue()).toBe('');
    const accessibility = await page.getByRole('dialog').ariaSnapshot();
    expect(accessibility).toContain('same.md');
    expect(accessibility).not.toMatch(/No file chosen|No file selected|未选择任何文件/);

    const nextChooser = page.waitForEvent('filechooser');
    await reselect.focus();
    await page.keyboard.press('Space');
    await (await nextChooser).setFiles({ name: 'same.md', mimeType: 'text/plain', buffer: Buffer.from('replacement content') });
    await page.locator('#learn-file-after').setInputFiles({ name: 'same.md', mimeType: 'text/plain', buffer: Buffer.from('after content') });
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => estimatePayloads.length).toBe(1);
    expect(estimatePayloads[0].compare_files).toEqual([
      { name: 'same.md', content: 'replacement content' },
      { name: 'same.md', content: 'after content' },
    ]);
  });

  it('shows real response text before enabling Start, without submitting a lesson', async () => {
    await renderDialog(page);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').textContent()).toBe(PREVIEW_PATCH);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(false);
    expect(await getPayloads(page)).toEqual([]);
    expect(estimatePayloads).toEqual([{ staged: true, unstaged: true, include_untracked: true, lang: 'en' }]);
  });

  it.each([
    { name: 'working', setup: async () => undefined, expected: { staged: true, unstaged: true, include_untracked: true } },
    { name: 'unstaged', setup: async () => { await page.locator('.learn-dialog__tile').nth(1).click(); }, expected: { unstaged: true, include_untracked: true } },
    { name: 'staged', setup: async () => { await page.locator('.learn-dialog__tile').nth(2).click(); }, expected: { staged: true } },
    { name: 'last', setup: async () => { await page.locator('.learn-dialog__tile').nth(3).click(); }, expected: { last: true } },
    { name: 'since', setup: async () => { await chooseAdvancedMode('learn-mode-since'); await page.locator('#learn-mode-since-value').fill('2 hours ago'); await page.locator('#learn-mode-author').fill('Ada'); }, expected: { since: '2 hours ago', author: 'Ada' } },
    { name: 'revision', setup: async () => { await chooseAdvancedMode('learn-mode-revision'); await page.locator('#learn-mode-revision-value').fill('HEAD~2..HEAD'); }, expected: { revision: 'HEAD~2..HEAD' } },
    { name: 'patch', setup: async () => { await selectSource('patch'); await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH); }, expected: { patch: PREVIEW_PATCH, force_learn: true } },
    { name: 'patch URL', setup: async () => { await chooseAdvancedMode('learn-mode-patch-url'); await page.locator('#learn-mode-patch-url-value').fill('https://example.test/change.diff'); }, expected: { patch_url: 'https://example.test/change.diff', force_learn: true } },
    { name: 'workspace files', setup: async () => { await chooseAdvancedMode('learn-mode-compare'); await page.locator('#learn-mode-compare-a').fill('old.py'); await page.locator('#learn-mode-compare-b').fill('new.py'); }, expected: { compare: ['old.py', 'new.py'], force_learn: true } },
    { name: 'directories', setup: async () => { await chooseAdvancedMode('learn-mode-compare-dir'); await page.locator('#learn-mode-compare-dir-a').fill('old/'); await page.locator('#learn-mode-compare-dir-b').fill('new/'); }, expected: { compare_dir: ['old/', 'new/'], force_learn: true } },
  ])('previews and submits the selected $name capture contract', async ({ setup, expected }) => {
    await renderDialog(page);
    await setup();
    await previewThenStart();
    expect(estimatePayloads.at(-1)).toEqual({ ...expected, lang: 'en' });
    expect(await getPayloads(page)).toEqual([{ ...expected, lang: 'en' }]);
    expect(await getRequestOptions(page)).toEqual([{ hasSignal: true, aborted: false }]);
    expect(await getCloseCount(page)).toBe(1);
  });

  it('uploads two same-name versions while preserving their exact content and the compare_files source', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await chooseFiles('SELECT * FROM users;\r\n', 'SELECT id FROM users;\r\n', 'query.sql');
    await previewThenStart();
    const expected = {
      compare_files: [
        { name: 'query.sql', content: 'SELECT * FROM users;\r\n' },
        { name: 'query.sql', content: 'SELECT id FROM users;\r\n' },
      ], force_learn: true, lang: 'en',
    };
    expect(estimatePayloads.at(-1)).toEqual(expected);
    expect(await getPayloads(page)).toEqual([expected]);
  });

  it('supports an empty before file and strips an UTF-8 BOM while reading text', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await chooseFiles('', '\ufeffnew text\n', 'notes.md');
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => estimatePayloads.length).toBe(1);
    expect(estimatePayloads[0].compare_files).toEqual([
      { name: 'notes.md', content: '' }, { name: 'notes.md', content: 'new text\n' },
    ]);
  });

  it.each([
    { name: 'binary bytes', file: 'bad.bin', data: Buffer.from([0, 1, 2]), error: 'binary data' },
    { name: 'invalid UTF-8', file: 'bad.txt', data: Buffer.from([0xff, 0xfe]), error: 'not valid UTF-8' },
    { name: 'oversized file', file: 'big.txt', data: Buffer.alloc(256 * 1024 + 1, 65), error: 'exceeds 256 KiB' },
    { name: 'Windows reserved name', file: 'COM¹.txt', data: Buffer.from('text'), error: 'plain filename' },
    { name: 'internal state filename', file: '.ahadiff', data: Buffer.from('text'), error: 'plain filename' },
    { name: 'leading whitespace', file: ' notes.md', data: Buffer.from('text'), error: 'plain filename' },
    { name: 'invisible filename character', file: 'note\u202e.txt', data: Buffer.from('text'), error: 'plain filename' },
  ])('rejects $name without requesting a preview', async ({ file, data, error }) => {
    await renderDialog(page, { initialSource: 'files' });
    await page.locator('#learn-file-before').setInputFiles({ name: file, mimeType: 'application/octet-stream', buffer: data });
    await expect.poll(() => page.locator('#learn-file-before-error').textContent()).toContain(error);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    expect(estimatePayloads).toHaveLength(0);
  });

  it('rejects serialized JSON over 1 MiB even when both files fit their raw byte limit', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await chooseFiles('\u0001'.repeat(180_000), '\u0002'.repeat(180_000), 'escaped.txt');
    await expect.poll(() => page.getByRole('alert').textContent()).toContain('more than 1 MiB');
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    expect(estimatePayloads).toHaveLength(0);
  });

  it('supports real drag and drop and reports multiple files without selecting an arbitrary one', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await page.locator('.learn-dialog__file-picker').first().evaluate((element) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['before'], 'draft.md', { type: 'text/plain' }));
      element.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }));
    });
    await expect.poll(() => page.locator('.learn-dialog__file-status strong').first().textContent()).toBe('draft.md');
    await page.locator('.learn-dialog__file-picker').first().evaluate((element) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['a'], 'a.md'));
      transfer.items.add(new File(['b'], 'b.md'));
      element.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }));
    });
    await expect.poll(() => page.locator('#learn-file-before-error').textContent()).toContain('exactly one file');
    await expect.poll(() => page.locator('.learn-dialog__file-status strong').count()).toBe(0);
  });

  it('does not let a slow earlier file read replace a newer selection of the same name', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await page.evaluate(() => {
      const original = FileReader.prototype.readAsArrayBuffer;
      FileReader.prototype.readAsArrayBuffer = function (blob: Blob): void {
        const reader = this;
        window.setTimeout(() => original.call(reader, blob), blob.size === 4 ? 180 : 0);
      };
    });
    await page.locator('#learn-file-before').setInputFiles({ name: 'same.py', mimeType: 'text/plain', buffer: Buffer.from('slow') });
    await page.locator('#learn-file-before').setInputFiles({ name: 'same.py', mimeType: 'text/plain', buffer: Buffer.from('newer') });
    await page.locator('#learn-file-after').setInputFiles({ name: 'same.py', mimeType: 'text/plain', buffer: Buffer.from('after!') });
    await expect.poll(() => page.locator('.learn-dialog__file-status strong').count()).toBe(2);
    await page.waitForTimeout(220);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => estimatePayloads.length).toBe(1);
    expect(estimatePayloads[0].compare_files).toEqual([
      { name: 'same.py', content: 'newer' }, { name: 'same.py', content: 'after!' },
    ]);
  });

  it('invalidates a successful preview when input or language options change', async () => {
    await renderDialog(page, { initialSource: 'patch' });
    await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(false);
    await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH + '\n');
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').count()).toBe(1);
    await openAdvanced();
    await page.locator('#learn-opt-lang').selectOption('zh-CN');
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
  });

  it('defaults output to the Chinese viewer locale and preserves an explicit Auto choice', async () => {
    await renderDialog(page, { locale: 'zh-CN', initialSource: 'patch' });
    await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => estimatePayloads.length).toBe(1);
    expect(estimatePayloads[0].lang).toBe('zh-CN');
    await openAdvanced();
    await page.locator('#learn-opt-lang').selectOption('auto');
    await previewThenStart();
    expect((await getPayloads(page))[0]?.lang).toBe('auto');
  });

  it('ignores an old preview response after switching sources', async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>(resolve => { release = resolve; });
    let requested = false;
    await page.route('**/api/learn/estimate', async route => {
      requested = true;
      await held;
      await route.fulfill({ json: makePreview({ preview_patch: 'STALE RESPONSE' }) }).catch(() => undefined);
    });
    await renderDialog(page);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => requested).toBe(true);
    await selectSource('files');
    release();
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    expect(await getPayloads(page)).toEqual([]);
  });

  it('preview errors fail closed, stay localizable and allow retry', async () => {
    await page.route('**/api/learn/estimate', route => route.fulfill({
      status: 422, json: { error_code: 'INPUT_VALIDATION', error: 'private backend details', status: 422 },
    }));
    await renderDialog(page, { locale: 'zh-CN' });
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.getByRole('alert').textContent()).toContain('尚未开始生成课程');
    expect(await page.getByRole('alert').textContent()).not.toContain('private backend details');
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    expect(await getPayloads(page)).toEqual([]);
    await page.route('**/api/learn/estimate', route => route.fulfill({ json: makePreview() }));
    await previewThenStart();
    expect(await getPayloads(page)).toHaveLength(1);
  });

  it('an empty diff cannot start a lesson, and truncated preview is explicitly labelled', async () => {
    await page.route('**/api/learn/estimate', route => route.fulfill({ json: makePreview({ preview_patch: '', file_count: 0, patch_bytes: 0 }) }));
    await renderDialog(page);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview').textContent()).toContain('No text changes');
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await page.route('**/api/learn/estimate', route => route.fulfill({ json: makePreview({ preview_truncated: true, diff_clipped: true }) }));
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview').textContent()).toContain('Only the first part');
    expect(await page.locator('.learn-dialog__preview').textContent()).toContain('only the captured portion');
  });

  it('keeps keyboard focus inside the dialog and restores the previous focus on close', async () => {
    await renderDialog(page, { open: false });
    await page.evaluate(() => {
      const button = document.createElement('button');
      button.id = 'focus-origin'; button.textContent = 'Open';
      document.body.appendChild(button); button.focus();
      window.__updateOpen(true);
    });
    await expect.poll(() => page.locator('[data-learn-source="git"]').evaluate(el => el === document.activeElement)).toBe(true);
    await page.keyboard.press('Shift+Tab');
    await expect.poll(() => page.locator('.learn-dialog__preview-button').evaluate(el => el === document.activeElement)).toBe(true);
    await page.keyboard.press('Tab');
    await expect.poll(() => page.locator('[data-learn-source="git"]').evaluate(el => el === document.activeElement)).toBe(true);
    await page.keyboard.press('Escape');
    expect(await getCloseCount(page)).toBe(1);
    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.locator('#focus-origin').evaluate(el => el === document.activeElement)).toBe(true);
  });

  it('closing clears uploaded and pasted content, aborts preview and restores existing inert state', async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>(resolve => { release = resolve; });
    let requested = false;
    await page.route('**/api/learn/estimate', async route => {
      requested = true; await held;
      await route.fulfill({ json: makePreview() }).catch(() => undefined);
    });
    await renderDialog(page, { initialSource: 'patch' });
    await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH);
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => requested).toBe(true);
    await page.keyboard.press('Escape');
    await page.evaluate(() => window.__updateOpen(false));
    release();
    await page.evaluate(() => window.__updateOpen(true));
    await selectSource('patch');
    await expect.poll(() => page.locator('#learn-mode-patch-text').inputValue()).toBe('');
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').count()).toBe(0);
    expect(await getPayloads(page)).toEqual([]);
  });

  it.each(['Escape', 'Cancel'] as const)('%s during actual POST keeps the acknowledgement and cancels its task', async closeAction => {
    let acknowledge: () => void = () => undefined;
    const held = new Promise<void>(resolve => { acknowledge = resolve; });
    let acceptedPosts = 0;
    const cancelledIds: string[] = [];
    await page.route('**/api/learn', async route => {
      acceptedPosts += 1;
      await held;
      await route.fulfill({ status: 202, json: { task_id: 'accepted-after-close' } });
    });
    await page.route('**/api/tasks/accepted-after-close/cancel', route => {
      cancelledIds.push('accepted-after-close');
      return route.fulfill({ json: { cancelled: true } });
    });
    await page.route('**/api/tasks/accepted-after-close/progress', route => route.fulfill({
      contentType: 'text/event-stream', body: 'event: error\ndata: {"event":"error","data":{"error":"poll instead"}}\n\n',
    }));
    await page.route('**/api/tasks/accepted-after-close', route => route.fulfill({ json: {
      task_id: 'accepted-after-close', task_type: 'learn', status: cancelledIds.length ? 'cancelled' : 'running',
      progress: { current: 0, total: 10, message: '' }, result_summary: null, error: null, error_code: null,
      created_at: '2026-09-08T00:00:00Z', started_at: null, completed_at: null,
      elapsed_seconds: null, recovery_hint: null,
    } }));
    await renderDialog(page, { useRealStore: true });
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(false);
    await page.locator('.learn-dialog__btn--primary').click();
    await expect.poll(() => acceptedPosts).toBe(1);
    if (closeAction === 'Escape') await page.keyboard.press('Escape');
    else await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.evaluate(() => window.__learnState().phase)).toBe('cancelling');
    acknowledge();
    await expect.poll(() => cancelledIds).toEqual(['accepted-after-close']);
    await expect.poll(() => page.evaluate(() => window.__learnState().taskId)).toBe('accepted-after-close');
    await expect.poll(() => page.evaluate(() => window.__learnState().phase), { timeout: 5000 }).toBe('cancelled');
    expect(acceptedPosts).toBe(1);
  });

  it.each(['submitting', 'running'] as const)('blocks all submissions while a task is %s', async phase => {
    await renderDialog(page, { phase });
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await expect.poll(() => page.locator('[data-learn-source="files"]').isDisabled()).toBe(true);
  });

  it('keeps scoped Git paths normalized and rejects absolute, internal and parent paths', async () => {
    await renderDialog(page);
    await openAdvanced();
    const field = page.locator('#learn-mode-path-scope');
    for (const invalid of ['../outside.py', '/tmp/file', 'C:\\file.py', '.git/config', '.ahadiff/config.toml', 'bad\tpath']) {
      await field.fill(invalid);
      await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    }
    await field.fill('src\\file.py\nsrc/file.py\n./docs/guide.md');
    await previewThenStart();
    expect((await getPayloads(page))[0]?.changed_paths).toEqual(['src/file.py', 'docs/guide.md']);
  });

  it('rejects more than 500 scoped paths and unsafe author filters before preview', async () => {
    await renderDialog(page);
    await openAdvanced();
    await page.locator('#learn-mode-path-scope').fill(Array.from({ length: 501 }, (_, index) => `src/${index}.py`).join('\n'));
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    await chooseAdvancedMode('learn-mode-since');
    await page.locator('#learn-mode-since-value').fill('yesterday');
    for (const author of ['--all', 'Ada\t--all']) {
      await page.locator('#learn-mode-author').fill(author);
      await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    }
    await page.locator('#learn-mode-author').fill('Ada');
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(false);
    expect(estimatePayloads).toHaveLength(0);
  });

  it('uses a native file picker when FileReader is unavailable and lets learners turn off the small-change override', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await page.evaluate(() => { Object.defineProperty(window, 'FileReader', { value: undefined, configurable: true }); });
    await chooseFiles('before', 'after', 'notes.md');
    await page.locator('.learn-dialog__explicit-learn input').uncheck();
    await previewThenStart();
    expect((await getPayloads(page))[0]).not.toHaveProperty('force_learn');
  });

  it('preserves pre-existing inert attributes when the modal closes', async () => {
    await renderDialog(page, { open: false });
    await page.evaluate(() => {
      const sibling = document.createElement('aside');
      sibling.id = 'already-inert'; sibling.setAttribute('inert', ''); document.body.appendChild(sibling);
      window.__updateOpen(true);
    });
    await expect.poll(() => page.locator('#root').getAttribute('inert')).toBe('');
    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.locator('#root').getAttribute('inert')).toBeNull();
    await expect.poll(() => page.locator('#already-inert').getAttribute('inert')).toBe('');
  });

  it('a pending file read cannot refill content after the dialog is closed', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await page.evaluate(() => {
      const original = FileReader.prototype.readAsArrayBuffer;
      FileReader.prototype.readAsArrayBuffer = function (blob: Blob): void {
        window.setTimeout(() => original.call(this, blob), 150);
      };
    });
    await page.locator('#learn-file-before').setInputFiles({ name: 'private.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic private text') });
    await page.keyboard.press('Escape');
    await page.evaluate(() => window.__updateOpen(false));
    await page.waitForTimeout(200);
    await page.evaluate(() => window.__updateOpen(true));
    await selectSource('files');
    await expect.poll(() => page.locator('.learn-dialog__file-status strong').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    expect(estimatePayloads).toHaveLength(0);
  });

  it('does not leak scoped paths or author filters when switching to a commit or uploaded files', async () => {
    await renderDialog(page);
    await openAdvanced();
    await page.locator('#learn-mode-path-scope').fill('src/limited.py');
    await chooseAdvancedMode('learn-mode-since');
    await page.locator('#learn-mode-since-value').fill('yesterday');
    await page.locator('#learn-mode-author').fill('Ada');
    await page.locator('.learn-dialog__tile').nth(3).click();
    await previewThenStart();
    expect((await getPayloads(page))[0]).toEqual({ last: true, lang: 'en' });
    await selectSource('files');
    await chooseFiles('old', 'new');
    await previewThenStart();
    expect((await getPayloads(page))[1]).not.toHaveProperty('author');
    expect((await getPayloads(page))[1]).not.toHaveProperty('changed_paths');
  });

  it.each([['', 'new.py'], ['old.py', ' '], ['', '']])('cannot preview a workspace file pair with an empty side (%s, %s)', async (before, after) => {
    await renderDialog(page);
    await chooseAdvancedMode('learn-mode-compare');
    await page.locator('#learn-mode-compare-a').fill(before);
    await page.locator('#learn-mode-compare-b').fill(after);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    expect(estimatePayloads).toHaveLength(0);
  });

  it.each([
    { mode: 'learn-mode-since', field: '#learn-mode-since-value', invalid: ['--all', 'yesterday\t--all', ''], valid: '2 hours ago' },
    { mode: 'learn-mode-revision', field: '#learn-mode-revision-value', invalid: ['--all', 'HEAD --stat', 'HEAD\tmain', ''], valid: 'HEAD~1..HEAD' },
    { mode: 'learn-mode-patch-url', field: '#learn-mode-patch-url-value', invalid: ['file:///etc/passwd', 'https://user:secret@example.test/diff', 'javascript:alert(1)', ''], valid: 'https://example.test/change.diff' },
  ])('validates the $mode input before preview', async ({ mode, field, invalid, valid }) => {
    await renderDialog(page);
    await chooseAdvancedMode(mode);
    for (const value of invalid) {
      await page.locator(field).fill(value);
      await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    }
    await page.locator(field).fill(valid);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(false);
    expect(estimatePayloads).toHaveLength(0);
  });

  it('rejects pasted stdin sentinel and counts patch limits in UTF-8 bytes', async () => {
    await renderDialog(page, { initialSource: 'patch' });
    for (const value of ['-', '汉'.repeat(22_000)]) {
      await page.locator('#learn-mode-patch-text').fill(value);
      await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    }
    await page.locator('#learn-mode-patch-text').fill(PREVIEW_PATCH);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(false);
  });

  it('carries explicit generation, language, privacy and dry-run options through the same preview and submit', async () => {
    await renderDialog(page);
    await openAdvanced();
    const flags = page.locator('.learn-dialog__options input[type="checkbox"]');
    await flags.nth(0).check(); await flags.nth(1).check(); await flags.nth(2).check();
    await page.locator('#learn-opt-lang').selectOption('zh-CN');
    await page.locator('#learn-opt-privacy').selectOption('strict_local');
    await previewThenStart();
    expect((await getPayloads(page))[0]).toEqual({
      staged: true, unstaged: true, include_untracked: true,
      force_learn: true, use_graphify: true, dry_run: true,
      lang: 'zh-CN', privacy_mode: 'strict_local',
    });
    expect(estimatePayloads[0]).toEqual((await getPayloads(page))[0]);
  });
  it.each(['en', 'zh-CN'] as const)('previews a standalone Markdown source without a fabricated diff in %s', async (locale) => {
    const document = '# 学习\n\nA synthetic source paragraph.\n';
    await page.route('**/api/learn/estimate', route => {
      estimatePayloads.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: makePreview({ preview_patch: '', preview_document: document, source_kind: 'document', patch_bytes: 0, source_bytes: 49 }) });
    });
    await renderDialog(page, { initialSource: 'document', locale });
    await page.locator('#learn-file-document').setInputFiles({ name: '学习.md', mimeType: 'text/markdown', buffer: Buffer.from(document) });
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview-diff').textContent()).toBe(document);
    expect(await page.locator('#learn-review-context').count()).toBe(0);
    await page.locator('.learn-dialog__btn--primary').click();
    expect((await getPayloads(page))[0]).toEqual({ document: { name: '学习.md', content: document }, force_learn: true, lang: locale });
    expect(estimatePayloads[0]).not.toHaveProperty('compare_files');
    expect(estimatePayloads[0]).not.toHaveProperty('patch');
  });

  it('rejects non-Markdown document files and clears private content on source switches', async () => {
    await renderDialog(page, { initialSource: 'document' });
    await page.locator('#learn-file-document').setInputFiles({ name: 'notes.pdf', mimeType: 'text/plain', buffer: Buffer.from('synthetic') });
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    await page.locator('#learn-file-document').setInputFiles({ name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# Synthetic') });
    await selectSource('files');
    await chooseFiles('before', 'after');
    await page.locator('#learn-review-context').fill('Synthetic reviewer notes');
    await previewThenStart();
    expect((await getPayloads(page))[0]).toMatchObject({ review_context: 'Synthetic reviewer notes' });
    expect((await getPayloads(page))[0]).not.toHaveProperty('document');
    await selectSource('document');
    expect(await page.locator('#learn-file-document-status strong').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
  });

  it('counts review notes in UTF-8 bytes and invalidates the preview when they change', async () => {
    await renderDialog(page, { initialSource: 'files' });
    await chooseFiles('before', 'after');
    await page.locator('#learn-review-context').fill('学'.repeat(2731));
    await expect.poll(() => page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
    await page.locator('#learn-review-context').fill('Synthetic notes');
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(false);
    await page.locator('#learn-review-context').fill('Changed synthetic notes');
    await expect.poll(() => page.locator('.learn-dialog__preview').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    expect(await getPayloads(page)).toEqual([]);
  });

  it.each(['en', 'zh-CN'] as const)('saves a baseline explicitly, reloads it and confirms deletion in %s', async (locale) => {
    const file = { name: '学习.md', content: '# Before\n' };
    const snapshotId = `snap_${'1'.repeat(32)}`;
    const contentHash = createHash('sha256').update(file.content).digest('hex');
    const record = { schema_version: 1, snapshot_id: snapshotId, name: 'Baseline', file_name: file.name,
      content: file.content, content_hash: contentHash, hash_scope: 'sanitized_utf8_nfc_lf',
      created_at: '2026-09-08T00:00:00Z', size_bytes: 9, source: 'explicit_file', sanitized: true };
    const { content: _content, ...fields } = record;
    const summary = { ...fields, status: 'ready', stored_bytes: 400, record_hash: createHash('sha256').update(JSON.stringify(record) + '\n').digest('hex') };
    let snapshots: typeof summary[] = [];
    const writes: Array<Record<string, unknown>> = [];
    let deletes = 0;
    await page.route('**/api/snapshots', async route => {
      if (route.request().method() === 'POST') {
        writes.push(route.request().postDataJSON() as Record<string, unknown>);
        snapshots = [summary];
        return route.fulfill({ status: 201, json: summary });
      }
      return route.fulfill({ json: { snapshots, max_count: 100, max_bytes: 16777216 } });
    });
    await page.route(`**/api/snapshots/${snapshotId}`, route => {
      if (route.request().method() === 'DELETE') {
        expect(route.request().postDataJSON()).toEqual({ expected_hash: summary.record_hash });
        deletes += 1;
        snapshots = [];
        return route.fulfill({ json: { snapshot_id: snapshotId, deleted: true } });
      }
      return route.fulfill({ json: record });
    });
    await renderDialog(page, { initialSource: 'snapshot', locale });
    await page.locator('#learn-snapshot-name').fill('Baseline');
    await page.locator('#learn-file-snapshot').setInputFiles({ name: file.name, mimeType: 'text/markdown', buffer: Buffer.from(file.content) });
    expect(writes).toEqual([]);
    await page.getByRole('button', { name: locale === 'en' ? 'Save baseline locally' : '保存本地基准', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toEqual({ name: 'Baseline', file });
    await expect.poll(() => page.locator('.learn-dialog__snapshot-item').count()).toBe(1);
    await renderDialog(page, { initialSource: 'snapshot', locale });
    await page.getByRole('button', { name: locale === 'en' ? 'Use baseline' : '使用此基准', exact: true }).click();
    await page.locator('#learn-file-after').setInputFiles({ name: file.name, mimeType: 'text/markdown', buffer: Buffer.from('# After\n') });
    await previewThenStart();
    expect((await getPayloads(page))[0]).toMatchObject({ snapshot_id: snapshotId, snapshot_hash: contentHash, snapshot_after: { name: file.name, content: '# After\n' } });
    expect((await getPayloads(page))[0]).not.toHaveProperty('compare_files');
    await page.getByRole('button', { name: locale === 'en' ? 'Delete snapshot' : '删除快照', exact: true }).click();
    expect(deletes).toBe(0);
    await page.getByRole('button', { name: locale === 'en' ? 'Delete this baseline' : '删除这份基准', exact: true }).click();
    await expect.poll(() => deletes).toBe(1);
    await expect.poll(() => page.locator('.learn-dialog__snapshot-item').count()).toBe(0);
  });

  it('keeps corrupt and unsupported snapshots visible without accepting them as comparison evidence', async () => {
    await page.route('**/api/snapshots', route => route.fulfill({ json: {
      max_count: 100, max_bytes: 16777216,
      snapshots: [
        { snapshot_id: `snap_${'2'.repeat(32)}`, status: 'corrupt', stored_bytes: 0, record_hash: null },
        { snapshot_id: `snap_${'3'.repeat(32)}`, status: 'unsupported', schema_version: 2, stored_bytes: 20, record_hash: 'f'.repeat(64) },
      ],
    } }));
    await renderDialog(page, { initialSource: 'snapshot' });
    await expect.poll(() => page.locator('.learn-dialog__snapshot-item').count()).toBe(2);
    for (const button of await page.getByRole('button', { name: 'Use baseline', exact: true }).all()) expect(await button.isDisabled()).toBe(true);
    expect(await page.locator('.learn-dialog__snapshot-item').first().getByRole('button', { name: 'Delete snapshot', exact: true }).isDisabled()).toBe(true);
    expect(await page.locator('.learn-dialog__preview-button').isDisabled()).toBe(true);
  });

  it.each(['en', 'zh-CN'] as const)('keeps the mixed quiz as the default in %s', async (locale) => {
    await renderDialog(page, { locale });
    await openAdvanced();
    const name = locale === 'en' ? 'Active transfer practice' : '主动迁移练习';
    const option = page.getByRole('checkbox', { name, exact: true });
    expect(await option.isChecked()).toBe(false);
    expect(await page.locator('#learn-opt-active-practice-hint').textContent()).toContain(locale === 'en' ? 'Off by default' : '默认关闭');
    await previewThenStart();
    expect((await getPayloads(page))[0]).not.toHaveProperty('active_practice');
    expect(estimatePayloads[0]).toEqual((await getPayloads(page))[0]);
  });

  it.each(['en', 'zh-CN'] as const)('requires a fresh preview and submits active practice explicitly in %s', async (locale) => {
    await renderDialog(page, { locale });
    await openAdvanced();
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(false);
    const option = page.getByRole('checkbox', { name: locale === 'en' ? 'Active transfer practice' : '主动迁移练习', exact: true });
    await option.check();
    await expect.poll(() => page.locator('.learn-dialog__preview').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await previewThenStart();
    expect((await getPayloads(page))[0]).toMatchObject({ active_practice: true, lang: locale });
    expect(estimatePayloads[1]).toEqual((await getPayloads(page))[0]);
  });

  it.each(['en', 'zh-CN'] as const)('turning active practice off restores the mixed payload and invalidates its preview in %s', async (locale) => {
    await renderDialog(page, { locale });
    await openAdvanced();
    const option = page.getByRole('checkbox', { name: locale === 'en' ? 'Active transfer practice' : '主动迁移练习', exact: true });
    await option.check();
    await page.locator('.learn-dialog__preview-button').click();
    await expect.poll(() => page.locator('.learn-dialog__preview').count()).toBe(1);
    await option.uncheck();
    await expect.poll(() => page.locator('.learn-dialog__preview').count()).toBe(0);
    await expect.poll(() => page.locator('.learn-dialog__btn--primary').isDisabled()).toBe(true);
    await previewThenStart();
    expect(estimatePayloads[0].active_practice).toBe(true);
    expect(estimatePayloads[1]).not.toHaveProperty('active_practice');
    expect((await getPayloads(page))[0]).not.toHaveProperty('active_practice');
  });

  it.each(['en', 'zh-CN'] as const)('resets active practice on source changes and after closing in %s', async (locale) => {
    await renderDialog(page, { locale });
    await openAdvanced();
    await page.locator('#learn-opt-active-practice').check();
    await selectSource('files');
    await openAdvanced();
    expect(await page.locator('#learn-opt-active-practice').isChecked()).toBe(false);
    await page.locator('#learn-opt-active-practice').check();
    await page.keyboard.press('Escape');
    await expect.poll(() => getCloseCount(page)).toBe(1);
    await page.evaluate(() => window.__updateOpen(false));
    await expect.poll(() => page.getByRole('dialog').count()).toBe(0);
    await page.evaluate(() => window.__updateOpen(true));
    await expect.poll(() => page.locator('[data-learn-source="git"]').getAttribute('aria-pressed')).toBe('true');
    await openAdvanced();
    expect(await page.locator('#learn-opt-active-practice').isChecked()).toBe(false);
    expect(await getPayloads(page)).toEqual([]);
  });

});
