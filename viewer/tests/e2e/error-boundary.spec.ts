import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

declare global {
  interface Window {
    __ahadiffCopiedPayload?: string;
    __ahadiffCopyTimerClears?: number;
  }
}

async function installLegacyClipboardProbe(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });

    const originalSetTimeout = window.setTimeout.bind(window);
    const originalClearTimeout = window.clearTimeout.bind(window);
    const copyTimers = new Set<number>();
    window.__ahadiffCopyTimerClears = 0;

    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      const id = originalSetTimeout(handler, timeout, ...args);
      if (timeout === 2000) copyTimers.add(Number(id));
      return id;
    }) as typeof window.setTimeout;

    window.clearTimeout = ((id?: number) => {
      if (id != null && copyTimers.has(Number(id))) {
        window.__ahadiffCopyTimerClears = (window.__ahadiffCopyTimerClears ?? 0) + 1;
        copyTimers.delete(Number(id));
      }
      return originalClearTimeout(id);
    }) as typeof window.clearTimeout;

    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: (command: string) => {
        if (command !== 'copy') return false;
        window.__ahadiffCopiedPayload =
          document.querySelector<HTMLTextAreaElement>('textarea')?.value ?? '';
        return true;
      },
    });
  });
}

async function installCrashingDashboard(page: Page) {
  await page.route(
    (url) => url.pathname === '/src/pages/DashboardPage.tsx',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          export default function DashboardPage() {
            throw new Error("api_key=sk-testsecret123456 Authorization: Bearer abcdef123456 /Users/alice/project/app.tsx file:///home/alice/project/app.tsx");
          }
        `,
      }),
  );
}

test.describe('ErrorBoundary browser regressions', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await installServeMock(page);
  });

  test('copies redacted diagnostics through the legacy clipboard fallback', async ({ page }) => {
    await installLegacyClipboardProbe(page);
    await installCrashingDashboard(page);

    await page.goto('/');

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('Something went wrong');
    await page.getByText('Technical details').click();

    const stack = await page.locator('.error-boundary__stack').innerText();
    expect(stack).toContain('api_key=[redacted]');
    expect(stack).toContain('Authorization=[redacted]');
    expect(stack).toContain('[local-path]');
    expect(stack).not.toContain('sk-testsecret123456');
    expect(stack).not.toContain('abcdef123456');
    expect(stack).not.toContain('/Users/alice');
    expect(stack).not.toContain('/home/alice');

    const copyButton = page.getByRole('button', { name: /Copy error|Copied/ });
    await copyButton.click();
    await expect(copyButton).toHaveText('Copied');

    const copiedPayload = await page.evaluate(() => window.__ahadiffCopiedPayload ?? '');
    expect(copiedPayload).toContain('AhaDiff error report');
    expect(copiedPayload).toContain('api_key=[redacted]');
    expect(copiedPayload).not.toContain('sk-testsecret123456');
    expect(copiedPayload).not.toContain('abcdef123456');
    expect(copiedPayload).not.toContain('/Users/alice');
    expect(copiedPayload).not.toContain('/home/alice');

    await copyButton.click();
    await expect
      .poll(() => page.evaluate(() => window.__ahadiffCopyTimerClears ?? 0))
      .toBeGreaterThan(0);
  });

  test('clears a pending copy timer when the fallback unmounts', async ({ page }) => {
    await installLegacyClipboardProbe(page);

    await page.goto('/');
    await page.evaluate(async (modulePath) => {
      const mod = await import(modulePath);
      mod.mountErrorBoundaryHarness();
    }, '/tests/fixtures/error-boundary-harness.tsx');

    const copyButton = page.getByRole('button', { name: /Copy error|Copied/ });
    await expect(copyButton).toBeVisible();
    await copyButton.click();
    await expect(copyButton).toHaveText('Copied');
    expect(await page.evaluate(() => window.__ahadiffCopyTimerClears ?? 0)).toBe(0);

    await page.getByRole('button', { name: 'Unmount boundary' }).click();
    await expect(page.getByRole('heading', { name: 'Unmounted' })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => window.__ahadiffCopyTimerClears ?? 0))
      .toBeGreaterThan(0);
  });
});
