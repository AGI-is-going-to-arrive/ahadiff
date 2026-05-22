import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';

const TEST_PATH = '/__landing-page-test.html';

const HARNESS_HTML = String.raw`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Landing page unit harness</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module">
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import { MemoryRouter } from 'react-router-dom';
      import LandingPage from '/src/pages/LandingPage.tsx';
      import { useLocaleStore } from '/src/state/locale-store.ts';
      import { useRunsStore } from '/src/state/runs-store.ts';

      let root;

      window.__renderLandingPage = ({ locale = 'en' } = {}) => {
        useLocaleStore.setState({ locale });
        useRunsStore.setState({
          runs: [],
          nextCursor: null,
          hasMore: false,
          details: {},
          detailLoadedAt: {},
          lastLoadedAt: null,
          lastSourceKind: undefined,
          loading: false,
          loadingMore: false,
          error: null,
          _generation: 0,
        });
        document.documentElement.lang = locale;

        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();
        root = createRoot(container);
        root.render(
          React.createElement(
            MemoryRouter,
            { initialEntries: ['/welcome'] },
            React.createElement(LandingPage),
          ),
        );
      };

      window.__cleanupLandingPage = () => {
        root?.unmount();
        root = undefined;
      };

      window.__landingPageReady = true;
    </script>
  </body>
</html>`;

interface RenderOptions {
  locale?: 'en' | 'zh-CN';
}

interface LandingScenario {
  diff: string;
  lesson?: string;
  runId?: string;
}

declare global {
  interface Window {
    __cleanupLandingPage: () => void;
    __landingPageReady?: boolean;
    __renderLandingPage: (options?: RenderOptions) => void;
  }
}

let server: ViteDevServer;
let browser: Browser;
let page: Page;
let baseUrl = '';

function makeRun(runId: string) {
  return {
    run_id: runId,
    source_ref: 'HEAD',
    source_kind: 'git_ref',
    content_lang: 'en',
    capability_level: 3,
    verdict: 'PASS',
    overall: 91,
    status: 'baseline',
    weakest_dim: 'evidence',
    created_at: '2026-05-22T00:00:00Z',
    degraded_flags: {},
  };
}

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

async function installApiMock(page: Page, scenario: LandingScenario): Promise<void> {
  const runId = scenario.runId ?? 'landing-unit-run';
  const lesson = scenario.lesson ?? '## What Changed\n\nThe right side is a lesson.';

  await page.route(
    /\/api\/auth\/token$/,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ token: 'landing-unit-token' }),
    }),
  );
  await page.route(
    /\/api\/runs(?:\?|$)/,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ runs: [makeRun(runId)] }),
    }),
  );
  await page.route(
    /\/api\/ratchet\/transparency$/,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        results: [],
        benchmark: { manifest: null, report: null, warnings: [] },
      }),
    }),
  );
  await page.route(
    /\/api\/tasks$/,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tasks: [] }),
    }),
  );
  await page.route(
    new RegExp(`/api/run/${runId}/diff$`),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: runId,
        artifact_type: 'diff',
        content: scenario.diff,
        content_lang: 'en',
      }),
    }),
  );
  await page.route(
    new RegExp(`/api/run/${runId}/lesson(?:\\?|$)`),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: runId,
        artifact_type: 'lesson',
        content: lesson,
        content_lang: 'en',
      }),
    }),
  );
}

async function renderLanding(page: Page, options: RenderOptions = {}): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__landingPageReady), undefined, { timeout: 5_000 });
  await page.evaluate((opts) => window.__renderLandingPage(opts), options);
}

function longDiff(): string {
  const lines = ['diff --git a/long.py b/long.py', '--- a/long.py', '+++ b/long.py', '@@ -1,5 +1,80 @@'];
  for (let i = 0; i < 80; i += 1) {
    lines.push(`+line_${i.toString().padStart(2, '0')}_` + 'abcdef1234567890'.repeat(8));
  }
  return lines.join('\n');
}

describe('LandingPage diff collapse', () => {
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

  it('collapses long diffs and cycles expanded state with keyboard controls', async () => {
    await installApiMock(page, { diff: longDiff() });
    await renderLanding(page);
    await page.waitForFunction(() => document.querySelector('.ba-diff-wrap pre')?.textContent?.includes('line_79'));

    const toggle = page.locator('.ba-diff-toggle');
    await expect.poll(() => toggle.count()).toBe(1);
    await expect.poll(() => toggle.getAttribute('aria-expanded')).toBe('false');
    await expect.poll(() => toggle.getAttribute('aria-controls')).toBe('landing-diff-content');
    await expect.poll(() => toggle.getAttribute('aria-label')).toMatch(/Before: Raw Git Diff: Show all/);
    await expect.poll(() => page.locator('.ba-diff-line-count').textContent()).toMatch(/Showing \d+ of 84 lines/);

    const collapsedMaxHeight = await page.locator('#landing-diff-content').evaluate(
      (el) => getComputedStyle(el).maxHeight,
    );
    expect(collapsedMaxHeight).not.toBe('none');

    await toggle.focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => toggle.getAttribute('aria-expanded')).toBe('true');
    await expect.poll(() => toggle.getAttribute('aria-label')).toBe('Before: Raw Git Diff: Collapse');
    await expect.poll(() => page.locator('.ba-diff-line-count').count()).toBe(0);
    await expect.poll(() => page.locator('#landing-diff-content').evaluate(
      (el) => getComputedStyle(el).maxHeight,
    )).toBe('none');

    await page.keyboard.press('Space');
    await expect.poll(() => toggle.getAttribute('aria-expanded')).toBe('false');
    await expect.poll(() => page.locator('.ba-diff-line-count').count()).toBe(1);
  }, 20_000);

  it('does not show collapse controls for short diffs', async () => {
    await installApiMock(page, {
      diff: ['diff --git a/short.py b/short.py', '--- a/short.py', '+++ b/short.py', '+ok'].join('\n'),
      runId: 'short-run',
    });
    await renderLanding(page);
    await page.waitForFunction(() => document.querySelector('.ba-diff-wrap pre')?.textContent?.includes('short.py'));

    await expect.poll(() => page.locator('.ba-diff-toggle').count()).toBe(0);
    await expect.poll(() => page.locator('.ba-diff-line-count').count()).toBe(0);
  }, 20_000);

  it('shows the empty diff state without collapse controls', async () => {
    await installApiMock(page, { diff: '   ', runId: 'empty-run' });
    await renderLanding(page);
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll('.ba-grid .hero-demo__artifact-empty'))
        .some((el) => el.textContent?.includes('no displayable diff artifact')),
    );

    await expect.poll(() => page.locator('.ba-diff-toggle').count()).toBe(0);
    await expect.poll(() => page.locator('.ba-diff-wrap').count()).toBe(0);
  }, 20_000);

  it('keeps the page usable when ResizeObserver is unavailable', async () => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));
    await page.addInitScript(() => {
      Object.defineProperty(window, 'ResizeObserver', { configurable: true, value: undefined });
    });

    await installApiMock(page, { diff: longDiff(), runId: 'no-resize-observer-run' });
    await renderLanding(page);
    await page.waitForFunction(() => document.querySelector('.ba-diff-wrap pre')?.textContent?.includes('line_79'));

    await expect.poll(() => page.locator('.ba-diff-toggle').count()).toBe(1);
    expect(pageErrors).toEqual([]);
  }, 20_000);
});
