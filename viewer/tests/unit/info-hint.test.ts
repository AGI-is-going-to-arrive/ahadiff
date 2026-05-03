import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';

const TEST_PATH = '/__info-hint-test.html';

const HARNESS_HTML = String.raw`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>InfoHint unit harness</title>
  </head>
  <body>
    <div id="root"></div>
    <script>
      window.__escapePropagated = false;
    </script>
    <script type="module">
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import InfoHint from '/src/components/InfoHint.tsx';

      let root;

      // React wrapper that detects Escape propagation via React's onKeyDown
      function PropagationWrapper({ label, children, position }) {
        const onKeyDown = (e) => {
          if (e.key === 'Escape') {
            window.__escapePropagated = true;
          }
        };
        return React.createElement(
          'div',
          { id: 'outer-wrapper', onKeyDown },
          React.createElement(InfoHint, { label, position }, children),
        );
      }

      window.__renderInfoHint = ({ label, children, position }) => {
        window.__escapePropagated = false;
        const container = document.getElementById('root');
        root?.unmount();
        container.replaceChildren();

        root = createRoot(container);
        const childNode = children
          ? React.createElement('span', { 'data-testid': 'custom-child' }, children)
          : undefined;
        root.render(
          React.createElement(PropagationWrapper, { label, position }, childNode),
        );
      };

      window.__cleanupInfoHint = () => {
        root?.unmount();
        root = undefined;
      };

      window.__infoHintReady = true;
    </script>
  </body>
</html>`;

interface RenderOptions {
  label: string;
  children?: string;
  position?: 'top' | 'bottom';
}

declare global {
  interface Window {
    __cleanupInfoHint: () => void;
    __escapePropagated: boolean;
    __infoHintReady?: boolean;
    __renderInfoHint: (options: RenderOptions) => void;
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

async function renderHint(page: Page, options: RenderOptions): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => Boolean(window.__infoHintReady));
  await page.evaluate((opts) => window.__renderInfoHint(opts), options);
}

describe('InfoHint tooltip component', () => {
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

  it('renders trigger button with correct aria-label', async () => {
    await renderHint(page, { label: 'Helpful hint' });

    const trigger = page.locator('.info-hint__trigger');
    await expect.poll(() => trigger.count()).toBe(1);
    await expect(trigger.getAttribute('aria-label')).resolves.toBe('More information');
    await expect(trigger.getAttribute('type')).resolves.toBe('button');
  });

  it('renders default icon when no children provided', async () => {
    await renderHint(page, { label: 'Default icon test' });

    const icon = page.locator('.info-hint__icon');
    await expect.poll(() => icon.count()).toBe(1);
    await expect(icon.getAttribute('aria-hidden')).resolves.toBe('true');
    // Unicode info circle U+24D8 rendered as &#9432;
    const text = await icon.textContent();
    expect(text).toBeTruthy();
  });

  it('renders custom children when passed', async () => {
    await renderHint(page, { label: 'Custom child test', children: 'Custom!' });

    const customChild = page.locator('[data-testid="custom-child"]');
    await expect.poll(() => customChild.count()).toBe(1);
    await expect(customChild.textContent()).resolves.toBe('Custom!');

    // Default icon should NOT be present
    const icon = page.locator('.info-hint__icon');
    await expect.poll(() => icon.count()).toBe(0);
  });

  it('shows tooltip (role="tooltip") on mouseEnter', async () => {
    await renderHint(page, { label: 'Hover tooltip' });

    // No tooltip initially
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(0);

    // Hover over the wrapper span
    await page.locator('.info-hint').hover();

    // Tooltip should appear
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);
    await expect(page.locator('[role="tooltip"]').textContent()).resolves.toBe('Hover tooltip');
  });

  it('hides tooltip on mouseLeave (after 120ms delay)', async () => {
    await renderHint(page, { label: 'Leave tooltip' });

    // Show tooltip
    await page.locator('.info-hint').hover();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Move mouse away from the component
    await page.mouse.move(0, 0);

    // Tooltip should still be visible briefly (120ms delay)
    // After the delay it should disappear
    await expect.poll(() => page.locator('[role="tooltip"]').count(), {
      timeout: 2000,
    }).toBe(0);
  });

  it('shows tooltip on focus', async () => {
    await renderHint(page, { label: 'Focus tooltip' });

    // No tooltip initially
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(0);

    // Focus the trigger button
    await page.locator('.info-hint__trigger').focus();

    // Tooltip should appear
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);
    await expect(page.locator('[role="tooltip"]').textContent()).resolves.toBe('Focus tooltip');
  });

  it('hides tooltip on blur', async () => {
    await renderHint(page, { label: 'Blur tooltip' });

    // Show via focus
    await page.locator('.info-hint__trigger').focus();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Blur by clicking elsewhere
    await page.locator('body').click({ position: { x: 0, y: 0 } });

    // Tooltip should disappear after delay
    await expect.poll(() => page.locator('[role="tooltip"]').count(), {
      timeout: 2000,
    }).toBe(0);
  });

  it('closes tooltip on Escape key', async () => {
    await renderHint(page, { label: 'Escape tooltip' });

    // Show via focus
    await page.locator('.info-hint__trigger').focus();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Press Escape
    await page.keyboard.press('Escape');

    // Tooltip should close immediately (no 120ms delay -- direct setOpen(false))
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(0);
  });

  it('Escape calls e.stopPropagation()', async () => {
    await renderHint(page, { label: 'Stop propagation test' });

    // Show via focus
    await page.locator('.info-hint__trigger').focus();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Reset propagation flag
    await page.evaluate(() => { window.__escapePropagated = false; });

    // Press Escape while tooltip is open
    await page.keyboard.press('Escape');

    // The outer wrapper should NOT have received the Escape event
    const propagated = await page.evaluate(() => window.__escapePropagated);
    expect(propagated).toBe(false);
  });

  it('aria-expanded is false when closed, true when open', async () => {
    await renderHint(page, { label: 'Expanded test' });

    const trigger = page.locator('.info-hint__trigger');

    // Initially closed
    await expect(trigger.getAttribute('aria-expanded')).resolves.toBe('false');

    // Open via hover
    await page.locator('.info-hint').hover();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Now expanded
    await expect(trigger.getAttribute('aria-expanded')).resolves.toBe('true');

    // Move away to close
    await page.mouse.move(0, 0);
    await expect.poll(() => page.locator('[role="tooltip"]').count(), {
      timeout: 2000,
    }).toBe(0);

    // Back to false
    await expect(trigger.getAttribute('aria-expanded')).resolves.toBe('false');
  });

  it('aria-describedby links to tooltip id when open, undefined when closed', async () => {
    await renderHint(page, { label: 'Describedby test' });

    const trigger = page.locator('.info-hint__trigger');

    // Closed: no aria-describedby
    const closedDescribedby = await trigger.getAttribute('aria-describedby');
    expect(closedDescribedby).toBeNull();

    // Open via focus
    await page.locator('.info-hint__trigger').focus();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Open: aria-describedby should match tooltip id
    const tooltipId = await page.locator('[role="tooltip"]').getAttribute('id');
    const openDescribedby = await trigger.getAttribute('aria-describedby');
    const openControls = await trigger.getAttribute('aria-controls');
    expect(tooltipId).toBeTruthy();
    expect(openDescribedby).toBe(tooltipId);
    expect(openControls).toBe(tooltipId);
  });

  it('applies info-hint__bubble--bottom position class by default', async () => {
    await renderHint(page, { label: 'Bottom position' });

    // Open tooltip
    await page.locator('.info-hint').hover();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    const bubble = page.locator('[role="tooltip"]');
    const classes = await bubble.getAttribute('class');
    expect(classes).toContain('info-hint__bubble--bottom');
    expect(classes).not.toContain('info-hint__bubble--top');
  });

  it('applies info-hint__bubble--top position class when position="top"', async () => {
    await renderHint(page, { label: 'Top position', position: 'top' });

    // Open tooltip
    await page.locator('.info-hint').hover();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    const bubble = page.locator('[role="tooltip"]');
    const classes = await bubble.getAttribute('class');
    expect(classes).toContain('info-hint__bubble--top');
    expect(classes).not.toContain('info-hint__bubble--bottom');
  });

  it('cleans up timeout on unmount (no lingering timers)', async () => {
    await renderHint(page, { label: 'Cleanup test' });
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Open tooltip, then start the hide timer by moving mouse away
    await page.locator('.info-hint').hover();
    await expect.poll(() => page.locator('[role="tooltip"]').count()).toBe(1);

    // Trigger mouseleave to start the 120ms timeout
    await page.mouse.move(0, 0);

    // Immediately unmount before timeout fires
    await page.evaluate(() => window.__cleanupInfoHint());

    // Verify no crash / no act() warnings
    // Component should be gone
    await expect.poll(() => page.locator('.info-hint').count()).toBe(0);

    // Wait past the 120ms to ensure no errors from orphaned timer
    await page.waitForTimeout(200);

    // Page should still be functional (no uncaught errors)
    // Give a tick for any async errors
    await page.waitForTimeout(50);
    expect(errors).toEqual([]);
  });
});
