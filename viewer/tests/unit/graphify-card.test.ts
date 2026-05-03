import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import type { GraphStatusResponse } from '../../src/api/types';

const TEST_PATH = '/__graphify-card-test.html';

const HARNESS_HTML = String.raw`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>GraphifyCard unit harness</title>
  </head>
  <body>
    <div id="root"></div>
    <script>
      window.__graphifyFetchCalls = [];
      window.__graphifySignals = [];
      window.__graphifyMode = { type: 'resolve', status: null };
      window.__graphifyClipboardAvailable = true;
      window.__graphifyClipboardWrites = [];
      window.__graphifyClearTimeoutCalls = 0;
      const __originalClearTimeout = window.clearTimeout.bind(window);
      window.clearTimeout = (id) => {
        window.__graphifyClearTimeoutCalls += 1;
        return __originalClearTimeout(id);
      };
      Object.defineProperty(window.navigator, 'clipboard', {
        configurable: true,
        get() {
          if (!window.__graphifyClipboardAvailable) return undefined;
          return {
            writeText(text) {
              window.__graphifyClipboardWrites.push(String(text));
              return Promise.resolve();
            },
          };
        },
      });
      window.fetch = (input, init = {}) => {
        const url = new URL(String(input), window.location.origin);
        if (url.pathname === '/api/auth/token') {
          return Promise.resolve(new Response(JSON.stringify({ token: 'unit-token' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        if (url.pathname === '/api/graph/status') {
          window.__graphifyFetchCalls.push({ path: url.pathname });
          window.__graphifySignals.push(init.signal ?? null);
          if (window.__graphifyMode.type === 'reject') {
            return Promise.reject(new Error('network error'));
          }
          if (window.__graphifyMode.type === 'pending') {
            return new Promise((_resolve, reject) => {
              init.signal?.addEventListener(
                'abort',
                () => reject(new DOMException('The operation was aborted.', 'AbortError')),
                { once: true },
              );
            });
          }
          return Promise.resolve(new Response(JSON.stringify(window.__graphifyMode.status), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        return Promise.reject(new Error('unexpected fetch: ' + url.pathname));
      };
    </script>
    <script type="module">
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import GraphifyCard from '/src/components/GraphifyCard.tsx';
      import { useLocaleStore } from '/src/state/locale-store.ts';
      import { useGraphStore } from '/src/state/graph-store.ts';

      let root;

      window.__renderGraphifyCard = ({ compact = false, locale = 'en', mode = 'resolve', status = null }) => {
        window.__graphifyFetchCalls = [];
        window.__graphifySignals = [];
        window.__graphifyMode = { type: mode, status };
        window.__graphifyClipboardAvailable = true;
        window.__graphifyClipboardWrites = [];
        window.__graphifyClearTimeoutCalls = 0;
        useGraphStore.setState({ status: null, loading: false, error: false, lastFetchedAt: 0 });
        useLocaleStore.setState({ locale });
        document.documentElement.lang = locale;

        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();
        root = createRoot(container);
        root.render(React.createElement(GraphifyCard, { compact }));
      };

      window.__cleanupGraphifyCard = () => {
        root?.unmount();
        root = undefined;
      };

      window.__graphifyReady = true;
    </script>
  </body>
</html>`;

interface RenderOptions {
  compact?: boolean;
  locale?: 'en' | 'zh-CN';
  mode?: 'resolve' | 'reject' | 'pending';
  status?: GraphStatusResponse;
}

declare global {
  interface Window {
    __cleanupGraphifyCard: () => void;
    __graphifyClearTimeoutCalls: number;
    __graphifyClipboardAvailable: boolean;
    __graphifyClipboardWrites: string[];
    __graphifyFetchCalls: Array<{ path: string }>;
    __graphifyReady?: boolean;
    __graphifySignals: Array<AbortSignal | null>;
    __renderGraphifyCard: (options: RenderOptions) => void;
  }
}

function makeStatus(overrides: Partial<GraphStatusResponse> = {}): GraphStatusResponse {
  return {
    enabled: true,
    source_exists: true,
    has_graph: true,
    freshness: 'fresh',
    node_count: 48,
    edge_count: 71,
    source_path: '.ahadiff/graphify/graph.json',
    provenance: null,
    ...overrides,
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

async function renderCard(page: Page, options: RenderOptions): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__graphifyReady));
  await page.evaluate((opts) => window.__renderGraphifyCard(opts), options);
}

async function graphFetchCount(page: Page): Promise<number> {
  return page.evaluate(() => window.__graphifyFetchCalls.length);
}

let server: ViteDevServer;
let browser: Browser;
let page: Page;
let baseUrl = '';

describe('GraphifyCard DOM rendering', () => {
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
    await browser.close();
    await server.close();
  });

  it('renders compact status with the catalog separator', async () => {
    await renderCard(page, { compact: true, status: makeStatus() });

    await page.waitForSelector('.graphify-card--compact');
    await expect.poll(() => graphFetchCount(page)).toBe(1);
    await expect(page.locator('.graphify-card__label').textContent()).resolves.toBe(
      'Graphify source',
    );
    await expect(page.locator('.graphify-badge').textContent()).resolves.toContain('Fresh');

    const counts = await page.locator('.graphify-card__counts').textContent();
    expect(counts).toContain('48 nodes');
    expect(counts).toContain('71 edges');
    expect(counts).toBe('48 nodes · 71 edges');
  });

  it('renders full status with source path and stat labels', async () => {
    await renderCard(page, { status: makeStatus({ freshness: 'stale' }) });

    await page.waitForSelector('.graphify-card[role="region"]');
    await expect(page.locator('.graphify-card__icon').textContent()).resolves.toBe('◈');
    await expect(page.locator('.graphify-card__title').textContent()).resolves.toBe(
      'Graphify source',
    );
    await expect(page.locator('.graphify-badge').textContent()).resolves.toContain('Stale');
    const body = page.locator('.graphify-card__body');
    await expect(body.textContent()).resolves.toContain('48 nodes');
    await expect(body.textContent()).resolves.toContain('71 edges');
    await expect(body.textContent()).resolves.toContain('.ahadiff/graphify/graph.json');
    const rows = page.locator('.graphify-card__row');
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(2);
  });

  it('renders long source_path without horizontal overflow', async () => {
    const longPath = '/very/deep/nested/project/directory/structure/that/goes/on/and/on/.ahadiff/graphify/knowledge-graph-with-extremely-long-filename.json';
    await renderCard(page, {
      status: makeStatus({ source_path: longPath }),
    });

    await page.waitForSelector('.graphify-card[role="region"]');
    const body = page.locator('.graphify-card__body');
    await expect(body.textContent()).resolves.toContain('knowledge-graph');

    const card = page.locator('.graphify-card');
    const overflow = await card.evaluate((el) => {
      return el.scrollWidth <= el.clientWidth;
    });
    expect(overflow).toBe(true);
  });

  it('does not render when Graphify is disabled', async () => {
    await renderCard(page, { status: makeStatus({ enabled: false }) });

    await expect.poll(() => graphFetchCount(page)).toBe(1);
    await expect.poll(() => page.locator('.graphify-card').count()).toBe(0);
  });

  it('does not render on fetch failure', async () => {
    await renderCard(page, { mode: 'reject' });

    await expect.poll(() => graphFetchCount(page)).toBe(1);
    await expect.poll(() => page.locator('.graphify-card').count()).toBe(0);
  });

  it('keeps card space reserved while status is pending', async () => {
    await renderCard(page, { compact: true, mode: 'pending' });
    await expect.poll(() => graphFetchCount(page)).toBe(1);

    const placeholder = page.locator('.graphify-card--placeholder');
    await expect.poll(() => placeholder.count()).toBe(1);
    await expect.poll(() => placeholder.evaluate((el) =>
      getComputedStyle(el).visibility,
    )).toBe('hidden');
  });

  it('renders empty-source state when the Graphify source is missing', async () => {
    await renderCard(page, {
      status: makeStatus({
        edge_count: 0,
        has_graph: false,
        node_count: 0,
        source_exists: false,
        source_path: null,
      }),
    });

    await page.waitForSelector('.graphify-card__empty');
    await expect(page.locator('.graphify-card__empty').textContent()).resolves.toBe(
      'No Graphify source has been imported yet',
    );
  });

  it('unmounts cleanly while status fetch is pending', async () => {
    await renderCard(page, { mode: 'pending' });
    await expect.poll(() => graphFetchCount(page)).toBe(1);

    await page.evaluate(() => window.__cleanupGraphifyCard());

    expect(await page.locator('.graphify-card').count()).toBe(0);
  });

  it('renders provenance rows when provenance data is present', async () => {
    await renderCard(page, {
      status: makeStatus({
        provenance: {
          graph_sha256: 'a'.repeat(64),
          import_time: '2026-05-01 12:00',
          parser_version: '0.3.1',
        },
      }),
    });

    await page.waitForSelector('.graphify-card[role="region"]');
    const body = page.locator('.graphify-card__body');
    await expect(body.textContent()).resolves.toContain('imported:');
    await expect(body.textContent()).resolves.toContain('v0.3.1');
    await expect(body.textContent()).resolves.toContain('aaaaaaaaaaaa…');

    const copyBtn = page.locator('.graphify-card__copy-btn');
    await expect.poll(() => copyBtn.count()).toBe(1);
  });

  it('copies the full SHA and clears the copied-state timer on unmount', async () => {
    const graphSha = 'b'.repeat(64);
    await renderCard(page, {
      status: makeStatus({
        provenance: {
          graph_sha256: graphSha,
          import_time: '2026-05-01 12:00',
          parser_version: '0.3.1',
        },
      }),
    });

    const copyBtn = page.locator('.graphify-card__copy-btn');
    await expect.poll(() => copyBtn.getAttribute('aria-live')).toBe('polite');
    await expect.poll(() => copyBtn.getAttribute('aria-label')).toBe('Copy full SHA-256 hash');
    await copyBtn.click();
    await expect.poll(() => copyBtn.textContent()).toBe('✓');
    await expect.poll(() => copyBtn.getAttribute('aria-label')).toBe('Copied');
    await expect.poll(() => page.evaluate(() => window.__graphifyClipboardWrites)).toEqual([
      graphSha,
    ]);

    const clearCountBefore = await page.evaluate(() => window.__graphifyClearTimeoutCalls);
    await page.evaluate(() => window.__cleanupGraphifyCard());
    await expect.poll(() => page.evaluate(() => window.__graphifyClearTimeoutCalls)).toBeGreaterThan(
      clearCountBefore,
    );
  });

  it('does not throw when the Clipboard API is unavailable', async () => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await renderCard(page, {
      status: makeStatus({
        provenance: {
          graph_sha256: 'c'.repeat(64),
          import_time: '2026-05-01 12:00',
          parser_version: '0.3.1',
        },
      }),
    });
    await page.evaluate(() => { window.__graphifyClipboardAvailable = false; });

    const copyBtn = page.locator('.graphify-card__copy-btn');
    await copyBtn.click();

    expect(pageErrors).toEqual([]);
    await expect.poll(() => page.evaluate(() => window.__graphifyClipboardWrites)).toEqual([]);
    await expect.poll(() => copyBtn.textContent()).toBe('Copy');
  });
});
