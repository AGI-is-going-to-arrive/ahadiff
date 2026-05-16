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

const LONG_DIFF_CONTENT = [
  'diff --git a/src/long.ts b/src/long.ts',
  '@@ -1,1 +1,181 @@',
  ' export const seed = 1;',
  ...Array.from({ length: 180 }, (_, index) =>
    `+export const generatedValue${String(index + 1).padStart(3, '0')} = ${index + 1};`,
  ),
].join('\n');

const LONG_CLAIMS_CONTENT = Array.from({ length: 24 }, (_, index) => {
  const line = Math.min(2 + index * 7, 175);
  const claimId = index === 20 ? 'c-scroll-target' : `c-long-${String(index).padStart(2, '0')}`;
  return JSON.stringify({
    claim_id: claimId,
    status: 'verified',
    statement:
      index === 20
        ? 'Selecting this lower claim should keep the right claim navigator available.'
        : `Generated long diff claim ${index}`,
    source_hunks: [{ file: 'src/long.ts', start: line, end: line, side: 'new' }],
    confidence: 0.88,
    concepts: ['long_diff_navigation'],
  });
}).join('\n');

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
      const longDiffContent = ${JSON.stringify(LONG_DIFF_CONTENT)};
      const longClaimsContent = ${JSON.stringify(LONG_CLAIMS_CONTENT)};
      let failClaims = false;
      let activeDiffContent = diffContent;
      let activeClaimsContent = claimsContent;
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
            content: activeDiffContent,
            content_lang: 'en',
          }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }));
        }
        if (url.pathname === '/api/run/run-1/claims') {
          if (failClaims) {
            return Promise.resolve(new Response(JSON.stringify({
              error_code: 'ARTIFACT_NOT_FOUND',
              error: 'claims artifact not found',
            }), {
              status: 404,
              headers: { 'content-type': 'application/json' },
            }));
          }
          return Promise.resolve(new Response(JSON.stringify({
            run_id: 'run-1',
            artifact_type: 'claims',
            content: activeClaimsContent,
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

      window.__renderDiffViewerPage = (options = {}) => {
        const { locale = 'en', claimsFail = false, longDiff = false } = options;
        failClaims = claimsFail;
        activeDiffContent = longDiff ? longDiffContent : diffContent;
        activeClaimsContent = longDiff ? longClaimsContent : claimsContent;
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
    __renderDiffViewerPage: (options?: {
      claimsFail?: boolean;
      locale?: 'en' | 'zh-CN';
      longDiff?: boolean;
    }) => void;
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

async function renderDiffPage(
  page: Page,
  options: { claimsFail?: boolean; longDiff?: boolean } = {},
): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__claimInspectorReady));
  await page.evaluate((opts) => window.__renderDiffViewerPage(opts), options);
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

  it('keeps the selected claim card and detail visible in the inspector', async () => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const claims = Array.from({ length: 22 }, (_, index) =>
      makeClaim({
        claim_id: index === 18 ? 'c-target' : `c-${String(index).padStart(2, '0')}`,
        statement:
          index === 18
            ? 'Selected claim detail should stay next to the selected card.'
            : `Background claim ${index}`,
        confidence: 0.9,
      }),
    );

    await renderInspector(page, { claims, selectedClaimId: 'c-target' });

    const selectedItem = page.locator('#claim-c-target');
    const selectedDetail = page.locator('#claim-detail-c-target');
    await expect.poll(() => selectedItem.count()).toBe(1);
    await expect.poll(() => selectedDetail.count()).toBe(1);
    await expect.poll(() => selectedDetail.textContent()).toContain(
      'Selected claim detail should stay next to the selected card.',
    );

    await page.waitForFunction(() => {
      const inspector = document.querySelector('.claim-inspector');
      const item = document.querySelector('#claim-c-target');
      const detail = document.querySelector('#claim-detail-c-target');
      if (!inspector || !item || !detail) return false;
      const inspectorBox = inspector.getBoundingClientRect();
      const itemBox = item.getBoundingClientRect();
      const detailBox = detail.getBoundingClientRect();
      return (
        itemBox.top >= inspectorBox.top &&
        itemBox.bottom <= inspectorBox.bottom &&
        detailBox.top >= inspectorBox.top &&
        detailBox.top - itemBox.bottom <= 16
      );
    });

    await expect
      .poll(() =>
        page.locator('.claim-inspector__list-item').evaluateAll((items) =>
          items.findIndex((item) => item.querySelector('#claim-c-target') !== null),
        ),
      )
      .toBe(18);
    await expect
      .poll(() =>
        page.locator('.claim-inspector__list-item').nth(18).evaluate((item) => {
          const button = item.querySelector('#claim-c-target');
          const detail = item.querySelector('#claim-detail-c-target');
          return Boolean(button && detail && button.nextElementSibling === detail);
        }),
      )
      .toBe(true);
  });

  it('keeps the claim navigator visible after jumping deep into a long diff', async () => {
    await page.setViewportSize({ width: 1280, height: 520 });
    await renderDiffPage(page, { longDiff: true });
    await page.locator('#claim-c-scroll-target').scrollIntoViewIfNeeded();
    await page.locator('#claim-c-scroll-target').click();

    await page.waitForFunction(() =>
      Boolean(
        document.querySelector(
          '.diff-line--claim-selected[data-line-anchor="src/long.ts:142"]',
        ),
      ),
    );
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
    await expect
      .poll(() =>
        page.locator('.claim-inspector').evaluate((inspector) => {
          const box = inspector.getBoundingClientRect();
          return box.top >= 0 && box.top < window.innerHeight && box.bottom > 0;
        }),
      )
      .toBe(true);
    await expect
      .poll(() =>
        page.locator('#claim-c-scroll-target').evaluate((item) => {
          const inspector = item.closest('.claim-inspector');
          if (!inspector) return false;
          const inspectorBox = inspector.getBoundingClientRect();
          const itemBox = item.getBoundingClientRect();
          return itemBox.top >= inspectorBox.top && itemBox.bottom <= inspectorBox.bottom;
        }),
      )
      .toBe(true);
  });

  it('renders selected source hunk next to the selected claim card', async () => {
    await renderDiffPage(page);
    await page.locator('.diff-line[data-claim-id="c007"]').first().click();

    const detail = page.locator('#claim-detail-c007');
    const sourcePreview = detail.locator('.claim-inspector__source-preview');
    await expect.poll(() => detail.count()).toBe(1);
    await expect.poll(() => sourcePreview.textContent()).toContain('Source hunk');
    await expect.poll(() => sourcePreview.textContent()).toContain('src/client.ts:2-4 · new');
    await expect
      .poll(() => sourcePreview.locator('.claim-inspector__source-preview-code').textContent())
      .toContain('+   2   async request(path: string, opts: ReqOpts = {}) {');
    expect(await page.locator('.diff-page__selected-hunk').count()).toBe(0);
    await expect
      .poll(() => page.locator('.diff-view').evaluate((el) => getComputedStyle(el).lineHeight))
      .toBe('22px');
  });

  it('keeps the diff visible when the claims artifact is unavailable', async () => {
    await renderDiffPage(page, { claimsFail: true });

    const warning = page.locator('.diff-page__claims-warning');
    await expect.poll(() => warning.textContent()).toContain('Claims unavailable');
    await expect.poll(() => warning.textContent()).toContain('claim anchors could not be loaded');
    await expect.poll(() => page.locator('.diff-view').count()).toBe(1);
    await expect.poll(() => page.locator('.claim-inspector__empty').textContent()).toContain(
      'Select a claim to inspect',
    );
  });
});
