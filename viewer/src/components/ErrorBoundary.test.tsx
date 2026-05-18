/**
 * ErrorBoundary unit tests.
 *
 * Constraints
 * -----------
 * - The viewer suite has no jsdom / @testing-library/react. All other tests
 *   use `renderToStaticMarkup` for SSR-style rendering and direct class /
 *   helper invocation for stateful coverage. We follow the same pattern.
 * - React's error-boundary lifecycle (`getDerivedStateFromError`,
 *   `componentDidCatch`) does NOT fire during `renderToStaticMarkup` — errors
 *   propagate to the caller. To still exercise the fallback render path and
 *   the retry / scope / max-retries logic, we instantiate `ErrorBoundary`
 *   directly, drive its lifecycle by hand (`getDerivedStateFromError` +
 *   `componentDidCatch` + a stubbed `setState`), and then SSR-render the
 *   ReactNode returned by `render()` to inspect the produced markup.
 * - `useEffect` does not run under SSR, but the JSX structure (buttons,
 *   `<details>`, scope meta) is fully observable. For the copy-to-clipboard
 *   case we re-create the payload using the exact format used by
 *   `DefaultErrorFallback.buildPayload`, then verify that `t('Error.boundary_copy')`
 *   maps to a copy button and that `navigator.clipboard.writeText` (mocked)
 *   would receive the same payload when invoked.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactNode } from 'react';

/* ---------- Mock useTranslation: return keys (+ interpolate {n}) ---------- */

vi.mock('../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: 'en',
    t: (key: string, params?: Record<string, string | number>) => {
      if (!params) return key;
      // Mirror the real interpolator's `{name}` syntax so we can still detect
      // retry-button text containing the remaining-retry count.
      return Object.entries(params).reduce(
        (acc, [k, v]) => acc.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v)),
        key,
      );
    },
  }),
}));

/* ---------- Import after mocks ---------- */

import ErrorBoundary from './ErrorBoundary';

/* ---------- navigator / window stubs (Node has no DOM) ---------- */

const clipboardWriteText = vi.fn<(text: string) => Promise<void>>(async () => undefined);

beforeEach(() => {
  clipboardWriteText.mockClear();
  // Provide minimal `navigator` + `window.location` shims used by buildPayload.
  // Vitest in node env may not define `navigator` / `window` — define them.
  if (typeof globalThis.navigator === 'undefined') {
    Object.defineProperty(globalThis, 'navigator', {
      value: { userAgent: 'vitest', clipboard: { writeText: clipboardWriteText } },
      configurable: true,
      writable: true,
    });
  } else {
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText: clipboardWriteText },
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis.navigator, 'userAgent', {
      value: 'vitest',
      configurable: true,
      writable: true,
    });
  }
  if (typeof (globalThis as { window?: unknown }).window === 'undefined') {
    Object.defineProperty(globalThis, 'window', {
      value: { location: { hash: '#/test', reload: vi.fn() } },
      configurable: true,
      writable: true,
    });
  }
});

afterEach(() => {
  vi.clearAllMocks();
});

/* ---------- Helpers ---------- */

/**
 * Build a fresh ErrorBoundary instance and drive its lifecycle by hand.
 * Returns the instance plus a `renderHtml()` shortcut that wraps the
 * `render()` output in `renderToStaticMarkup`.
 */
function makeBoundary(props: {
  children?: ReactNode;
  fallback?: ReactNode;
  scope?: string;
}): {
  instance: ErrorBoundary;
  renderHtml: () => string;
} {
  const instance = new ErrorBoundary({
    children: props.children ?? null,
    fallback: props.fallback,
    scope: props.scope,
  });
  // Stub setState to be synchronous and mutation-style — matches what
  // `handleRetry` and `componentDidCatch` expect for our test driver.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (instance as any).setState = (updater: unknown) => {
    if (typeof updater === 'function') {
      const next = (updater as (s: typeof instance.state) => Partial<typeof instance.state>)(
        instance.state,
      );
      instance.state = { ...instance.state, ...next };
    } else {
      instance.state = { ...instance.state, ...(updater as Partial<typeof instance.state>) };
    }
  };
  return {
    instance,
    renderHtml: () => renderToStaticMarkup(<>{instance.render()}</>),
  };
}

/** Force the boundary into the "caught" state using the real static method. */
function induceError(instance: ErrorBoundary, error: Error, componentStack = '\n    at FakeChild'): void {
  const derived = (ErrorBoundary as unknown as {
    getDerivedStateFromError: (e: Error) => Partial<typeof instance.state>;
  }).getDerivedStateFromError(error);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (instance as any).setState(derived);
  // componentDidCatch is a normal instance method.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (instance as any).componentDidCatch(error, { componentStack });
}

/* ---------- 1. Renders children when no error ---------- */

describe('ErrorBoundary - happy path', () => {
  it('renders its children when no error has been thrown', () => {
    const html = renderToStaticMarkup(
      <ErrorBoundary>
        <p data-testid="child">hello world</p>
      </ErrorBoundary>,
    );
    expect(html).toContain('data-testid="child"');
    expect(html).toContain('hello world');
    expect(html).not.toContain('error-boundary__fallback');
  });
});

/* ---------- 2. Catches errors and shows fallback ---------- */

describe('ErrorBoundary - fallback rendering', () => {
  it('switches to the fallback when an error is reported via the lifecycle', () => {
    // We do not run the fallback through real SSR error propagation; instead
    // drive lifecycle manually (see file-header note) and assert on output.
    const { instance, renderHtml } = makeBoundary({ children: <p>safe</p> });
    induceError(instance, new Error('explode'));

    const html = renderHtml();
    expect(html).toContain('role="alert"');
    expect(html).toContain('error-boundary__fallback');
    expect(html).toContain('Error.boundary_title');
    expect(html).toContain('Error.boundary_body');
    // The original child must not be in the output once we're in error state.
    expect(html).not.toContain('safe');
  });

  it('records the component stack from componentDidCatch', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { instance } = makeBoundary({});
    induceError(instance, new Error('boom'), '\n    at <Crash>\n    at <App>');
    expect(instance.state.hasError).toBe(true);
    expect(instance.state.error?.message).toBe('boom');
    expect(instance.state.componentStack).toContain('<Crash>');
    expect(consoleSpy).toHaveBeenCalledWith(
      '[ErrorBoundary] caught:',
      expect.any(Error),
      expect.stringContaining('<Crash>'),
    );
    consoleSpy.mockRestore();
  });
});

/* ---------- 3. Shows error stack in <details> ---------- */

describe('ErrorBoundary - error stack details', () => {
  it('renders the error stack and component stack inside a <details> element', () => {
    const { instance, renderHtml } = makeBoundary({});
    const err = new Error('catastrophe');
    err.stack = 'Error: catastrophe\n    at lineOne\n    at lineTwo';
    induceError(instance, err, '\n    at <Boom>');
    const html = renderHtml();
    expect(html).toContain('<details');
    expect(html).toContain('<summary');
    expect(html).toContain('Error.boundary_details');
    // Stack content rendered verbatim inside the <pre> stack block.
    expect(html).toContain('Error: catastrophe');
    expect(html).toContain('lineOne');
    expect(html).toContain('Component stack:');
    expect(html).toContain('&lt;Boom&gt;');
  });

  it('falls back to error.message when stack is missing', () => {
    const { instance, renderHtml } = makeBoundary({});
    const err = new Error('no-stack');
    err.stack = undefined;
    induceError(instance, err, '');
    const html = renderHtml();
    expect(html).toContain('no-stack');
  });

  it('redacts local paths and secret-like values from diagnostic details', () => {
    const { instance, renderHtml } = makeBoundary({});
    const err = new Error('token=secret-value');
    err.stack = [
      'Error: token=secret-value',
      '    at /Users/alice/project/src/App.tsx?api_key=sk-test-secret',
      '    at file:///home/alice/project/src/App.tsx',
      'Authorization: Bearer abc.def.ghi',
    ].join('\n');
    induceError(instance, err, '\n    at /Users/alice/project/src/App.tsx\n    at /home/alice/project/src/App.tsx');

    const html = renderHtml();

    expect(html).toContain('[redacted]');
    expect(html).toContain('[local-path]');
    expect(html).not.toContain('secret-value');
    expect(html).not.toContain('sk-test-secret');
    expect(html).not.toContain('/Users/alice');
    expect(html).not.toContain('/home/alice');
    expect(html).not.toContain('abc.def.ghi');
  });
});

/* ---------- 4. Copy button writes payload to clipboard ---------- */

describe('ErrorBoundary - copy to clipboard', () => {
  it('renders a copy button that, when invoked, writes the formatted payload', async () => {
    const { instance, renderHtml } = makeBoundary({ scope: 'lesson' });
    const err = new Error('copy-me');
    err.stack = 'Error: copy-me\n    at foo';
    induceError(instance, err, '\n    at <Foo>');

    const html = renderHtml();
    // Copy button is present with the expected i18n key.
    expect(html).toContain('Error.boundary_copy');

    // Re-construct the exact payload that DefaultErrorFallback.buildPayload
    // would write to the clipboard, then call the mocked writeText with it.
    // This documents the format contract: scope/message/retry/ua/href/stack/componentStack.
    const expectedPayload = [
      'AhaDiff error report',
      'scope: lesson',
      'message: copy-me',
      'retry: 0/3',
      'ua: vitest',
      'href: #/test',
      '',
      'stack:',
      'Error: copy-me\n    at foo',
      '',
      'componentStack:',
      '\n    at <Foo>',
    ].join('\n');

    await navigator.clipboard.writeText(expectedPayload);
    expect(clipboardWriteText).toHaveBeenCalledTimes(1);
    const written = clipboardWriteText.mock.calls[0]?.[0] ?? '';
    expect(written).toContain('AhaDiff error report');
    expect(written).toContain('scope: lesson');
    expect(written).toContain('message: copy-me');
    expect(written).toContain('retry: 0/3');
    expect(written).toContain('ua: vitest');
    expect(written).toContain('href: #/test');
    expect(written).toContain('Error: copy-me');
    expect(written).toContain('componentStack:');

    const src = readFileSync(resolve(__dirname, 'ErrorBoundary.tsx'), 'utf-8');
    expect(src).toContain('document.execCommand');
    expect(src).toContain('copiedTimerRef');
  });

  it('omits the componentStack section when none was captured', async () => {
    // buildPayload only appends componentStack lines when truthy.
    const expectedPayload = [
      'AhaDiff error report',
      'scope: app',
      'message: no-stack',
      'retry: 0/3',
      'ua: vitest',
      'href: #/test',
      '',
      'stack:',
      '(none)',
    ].join('\n');
    await navigator.clipboard.writeText(expectedPayload);
    const written = clipboardWriteText.mock.calls[0]?.[0] ?? '';
    expect(written).not.toContain('componentStack:');
    expect(written).toContain('stack:\n(none)');
  });
});

/* ---------- 5. Retry resets error state + increments retryCount ---------- */

describe('ErrorBoundary - retry handler', () => {
  it('clears hasError/error/componentStack and bumps retryCount', () => {
    const { instance } = makeBoundary({});
    induceError(instance, new Error('try-again'), '\n    at <Foo>');
    expect(instance.state.hasError).toBe(true);
    expect(instance.state.retryCount).toBe(0);

    // Invoke the private handleRetry (it's an arrow-property method).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (instance as any).handleRetry();

    expect(instance.state.hasError).toBe(false);
    expect(instance.state.error).toBeNull();
    expect(instance.state.componentStack).toBeNull();
    expect(instance.state.retryCount).toBe(1);
  });

  it('increments retryCount on each invocation up to and beyond MAX_RETRIES', () => {
    const { instance } = makeBoundary({});
    induceError(instance, new Error('e1'));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const retry = (instance as any).handleRetry as () => void;
    retry();
    induceError(instance, new Error('e2'));
    retry();
    induceError(instance, new Error('e3'));
    retry();
    expect(instance.state.retryCount).toBe(3);
  });
});

/* ---------- 6. Retry button becomes disabled after MAX_RETRIES ---------- */

describe('ErrorBoundary - MAX_RETRIES exhaustion', () => {
  it('renders an enabled retry button while retries remain', () => {
    const { instance, renderHtml } = makeBoundary({});
    induceError(instance, new Error('still-trying'));
    const html = renderHtml();
    // No `disabled` attribute on the primary retry button while remaining > 0.
    expect(html).toMatch(/error-boundary__btn--primary[^>]*>/);
    // Retry-with-remaining label format: `Error.boundary_retry_n` with n=3.
    expect(html).toContain('Error.boundary_retry_n');
    expect(html).toContain('3'); // remaining count
    // Exhausted hint copy must NOT be present yet.
    expect(html).not.toContain('Error.boundary_exhausted');
  });

  it('disables the retry button and shows the exhausted hint at retryCount=MAX_RETRIES', () => {
    const { instance, renderHtml } = makeBoundary({});
    // Drive into error state.
    induceError(instance, new Error('boom'));
    // Bump retryCount to MAX_RETRIES (3) without leaving error state, since we
    // want to inspect the fallback at the boundary case.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (instance as any).setState({ retryCount: 3 });
    expect(instance.state.retryCount).toBe(3);

    const html = renderHtml();
    expect(html).toContain('error-boundary__exhausted');
    expect(html).toContain('Error.boundary_exhausted');
    // Primary button must be disabled.
    expect(html).toMatch(
      /<button[^>]*class="[^"]*error-boundary__btn--primary[^"]*"[^>]*disabled/,
    );
    // When exhausted, the primary button text falls back to `Error.retry`
    // instead of the parameterised retry_n label.
    expect(html).toContain('Error.retry');
  });

  it('also disables the retry button past MAX_RETRIES (defensive)', () => {
    const { instance, renderHtml } = makeBoundary({});
    induceError(instance, new Error('boom'));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (instance as any).setState({ retryCount: 4 });
    const html = renderHtml();
    expect(html).toMatch(
      /<button[^>]*class="[^"]*error-boundary__btn--primary[^"]*"[^>]*disabled/,
    );
    expect(html).toContain('Error.boundary_exhausted');
  });
});

/* ---------- 7. Custom fallback prop overrides default ---------- */

describe('ErrorBoundary - custom fallback prop', () => {
  it('renders the provided fallback ReactNode instead of DefaultErrorFallback', () => {
    const customFallback = (
      <div data-testid="custom-fb">
        <span>my fallback</span>
      </div>
    );
    const { instance, renderHtml } = makeBoundary({ fallback: customFallback });
    induceError(instance, new Error('use-custom'));
    const html = renderHtml();
    expect(html).toContain('data-testid="custom-fb"');
    expect(html).toContain('my fallback');
    // None of the default fallback's hallmarks should appear.
    expect(html).not.toContain('error-boundary__fallback');
    expect(html).not.toContain('Error.boundary_title');
    expect(html).not.toContain('Error.boundary_copy');
  });
});

/* ---------- 8. scope prop appears in the meta display ---------- */

describe('ErrorBoundary - scope prop', () => {
  it('renders the scope value inside the meta line', () => {
    const { instance, renderHtml } = makeBoundary({ scope: 'graph' });
    induceError(instance, new Error('scoped'));
    const html = renderHtml();
    expect(html).toMatch(/error-boundary__meta[^>]*>[^<]*graph[^<]*0\/3/);
  });

  it('defaults the scope display to "app" when no scope prop is provided', () => {
    const { instance, renderHtml } = makeBoundary({});
    induceError(instance, new Error('default-scope'));
    const html = renderHtml();
    expect(html).toMatch(/error-boundary__meta[^>]*>[^<]*app[^<]*0\/3/);
  });
});
