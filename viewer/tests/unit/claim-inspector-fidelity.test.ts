import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import type { ClaimInspectorClaim } from '../../src/components/ClaimInspector';

const TEST_PATH = '/__claim-inspector-fidelity-test.html';

const DIFF_CONTENT = [
  'diff --git a/src/client.ts b/src/client.ts',
  '@@ -1,2 +1,5 @@',
  ' export class ApiClient {',
  '+  async request(path: string, opts: ReqOpts = {}) {',
  '+    const max = opts.retries ?? 4',
  '+    await sleep(max)',
  ' }',
].join('\n');

const CLAIMS_CONTENT = [
  JSON.stringify({
    claim_id: 'c007',
    status: 'verified',
    statement: 'Retry loop uses bounded retry options.',
    source_hunks: [{ file: 'src/client.ts', start: 2, end: 4, side: 'new' }],
    confidence: 0.91,
    concepts: ['retry', 'retry ', 'bounded_retry'],
  }),
].join('\n');

const HARNESS_HTML = String.raw`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>ClaimInspector fidelity harness</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module">
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import { MemoryRouter, Route, Routes } from 'react-router-dom';
      import ClaimInspector from '/src/components/ClaimInspector.tsx';
      import DiffViewerPage from '/src/pages/DiffViewerPage.tsx';
      import { resetToken } from '/src/api/client.ts';
      import { useLocaleStore } from '/src/state/locale-store.ts';

      const diffContent = ${JSON.stringify(DIFF_CONTENT)};
      const claimsContent = ${JSON.stringify(CLAIMS_CONTENT)};
      let root;

      function mount(node) {
        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();
        root = createRoot(container);
        root.render(node);
      }

      window.fetch = (input, init = {}) => {
        const url = new URL(String(input), window.location.origin);
        if (url.pathname === '/api/auth/token') {
          return Promise.resolve(new Response(JSON.stringify({ token: 'unit-token' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        if (url.pathname === '/api/run/run-1/diff') {
          return Promise.resolve(new Response(JSON.stringify({
            run_id: 'run-1',
            artifact_type: 'diff',
            content: diffContent,
            content_lang: 'en',
          }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        if (url.pathname === '/api/run/run-1/claims') {
          return Promise.resolve(new Response(JSON.stringify({
            run_id: 'run-1',
            artifact_type: 'claims',
            content: claimsContent,
            content_lang: 'en',
          }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        return Promise.reject(new Error('unexpected fetch: ' + url.pathname));
      };

      window.__renderClaimInspector = ({ claims = [], selectedClaimId = null, locale = 'en' }) => {
        useLocaleStore.setState({ locale });
        document.documentElement.lang = locale;
        mount(React.createElement(ClaimInspector, {
          claims,
          selectedClaimId,
          onSelect: () => {},
          onCopyAnchor: () => {},
        }));
      };

      window.__renderDiffViewerPage = ({ locale = 'en' } = {}) => {
        resetToken();
        useLocaleStore.setState({ locale });
        document.documentElement.lang = locale;
        mount(
          React.createElement(
            MemoryRouter,
            { initialEntries: ['/diff/run-1'] },
            React.createElement(
              Routes,
              null,
              React.createElement(Route, {
                path: '/diff/:runId',
                element: React.createElement(DiffViewerPage),
              }),
            ),
          ),
        );
      };

      window.__claimInspectorReady = true;
    </script>
  </body>
</html>`;

interface RenderInspectorOptions {
  claims?: ClaimInspectorClaim[];
  locale?: 'en' | 'zh-CN';
  selectedClaimId?: string | null;
}

declare global {
  interface Window {
    __claimInspectorReady?: boolean;
    __renderClaimInspector: (options: RenderInspectorOptions) => void;
    __renderDiffViewerPage: (options?: { locale?: 'en' | 'zh-CN' }) => void;
  }
}

function makeClaim(overrides: Partial<ClaimInspectorClaim> = {}): ClaimInspectorClaim {
  return {
    claim_id: 'c001',
    verdict: 'verified',
    file: 'src/client.ts',
    line_start: 2,
    line_end: 4,
    statement: 'Retry loop uses bounded retry options.',
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

async function renderInspector(page: Page, options: RenderInspectorOptions): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__claimInspectorReady));
  await page.evaluate((opts) => window.__renderClaimInspector(opts), options);
  await page.waitForSelector('.claim-inspector');
}

async function renderDiffPage(page: Page): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__claimInspectorReady));
  await page.evaluate(() => window.__renderDiffViewerPage());
  await page.waitForSelector('.diff-view');
}

let server: ViteDevServer;
let browser: Browser;
let page: Page;
let baseUrl = '';

describe('ClaimInspector V6 fidelity', () => {
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

  it('renders the empty state without filters', async () => {
    await renderInspector(page, { claims: [] });

    await expect.poll(() => page.locator('.claim-inspector__empty').textContent()).toContain(
      'Select a claim to inspect',
    );
    expect(await page.locator('.claim-inspector__chip').count()).toBe(0);
  });

  it('uses mutually exclusive V6 filter chips and groups rejected claims', async () => {
    await renderInspector(page, {
      claims: [
        makeClaim({ claim_id: 'c-verified', verdict: 'verified' }),
        makeClaim({ claim_id: 'c-weak', verdict: 'weak' }),
        makeClaim({ claim_id: 'c-contradicted', verdict: 'contradicted' }),
        makeClaim({ claim_id: 'c-rejected', verdict: 'rejected' }),
      ],
    });

    await expect.poll(() => page.locator('.claim-inspector__item').count()).toBe(2);
    await page.getByRole('button', { name: /Rejected\s+2/ }).click();

    await expect.poll(() => page.locator('.claim-inspector__item').count()).toBe(2);
    await expect
      .poll(() => page.locator('.claim-inspector__item').allTextContents())
      .toEqual([
        expect.stringContaining('c-contradicted'),
        expect.stringContaining('c-rejected'),
      ]);
    expect(await page.locator('.claim-inspector__chip[aria-pressed="true"]').count()).toBe(1);
    expect(
      await page.locator('.claim-inspector__item--contradicted').first().count(),
    ).toBe(1);
    expect(await page.locator('.claim-inspector__item--rejected').first().count()).toBe(1);
  });

  it('suppresses invalid confidence values', async () => {
    await renderInspector(page, {
      claims: [makeClaim({ confidence: 1.2 })],
      selectedClaimId: 'c001',
    });

    expect(await page.locator('.claim-inspector__item-conf').count()).toBe(0);
    expect(await page.locator('.claim-inspector__conf-score').count()).toBe(0);
  });

  it('deduplicates stable concept tags while preserving long labels', async () => {
    const longConcept = 'retry_strategy_with_exponential_backoff_and_jitter_for_remote_calls';
    await renderInspector(page, {
      claims: [makeClaim({ concepts: ['retry', 'retry ', longConcept, longConcept] })],
      selectedClaimId: 'c001',
    });

    // Collapsed claim cards no longer render concept tags inline (they show
    // only id + badge + truncated summary). Concepts are shown only in the
    // expanded detail row of the selected claim.
    expect(
      await page
        .locator('.claim-inspector__item .claim-inspector__concept-tag')
        .count(),
    ).toBe(0);
    await expect
      .poll(() =>
        page
          .locator('.claim-inspector__concepts-list .claim-inspector__concept-tag')
          .allTextContents(),
      )
      .toEqual(['retry', longConcept]);
  });

  it('keeps the single-claim layout compact without filter chips', async () => {
    await renderInspector(page, {
      claims: [makeClaim({ claim_id: 'c-single' })],
    });

    expect(await page.locator('.claim-inspector__chip').count()).toBe(0);
    expect(await page.locator('.claim-inspector__item').count()).toBe(1);
    await expect
      .poll(() => page.locator('.claim-inspector__item').textContent())
      .toContain('c-single');
  });

  it('keeps a single rejected claim visible without a recovery filter chip', async () => {
    await renderInspector(page, {
      claims: [makeClaim({ claim_id: 'c-rejected-single', verdict: 'rejected' })],
    });

    expect(await page.locator('.claim-inspector__chip').count()).toBe(0);
    expect(await page.locator('.claim-inspector__item').count()).toBe(1);
    await expect
      .poll(() => page.locator('.claim-inspector__item').textContent())
      .toContain('c-rejected-single');
  });

  it('renders selected source hunk outside the 22px diff area', async () => {
    await renderDiffPage(page);
    await page.locator('.diff-line[data-claim-id="c007"]').first().click();

    const panel = page.locator('.diff-page__selected-hunk');
    await expect.poll(() => panel.count()).toBe(1);
    await expect.poll(() => panel.textContent()).toContain('Selected source hunk');
    await expect.poll(() => panel.textContent()).toContain('c007 · src/client.ts:2-4');
    expect(await page.locator('.diff-view .diff-page__selected-hunk').count()).toBe(0);
    await expect
      .poll(() => page.locator('.diff-view').evaluate((el) => getComputedStyle(el).lineHeight))
      .toBe('22px');
  });
});
