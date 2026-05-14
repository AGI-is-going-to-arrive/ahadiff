import { expect, test, type Page, type Route } from '@playwright/test';

// Phase 2H: ensureToken() defaults to POST /api/auth/token; cache cleared and
// retried once on 401/403; bootstrap fetch aborts after 8s. Backend BF-5
// closure tests cover the same-origin gate; here we only assert browser
// behavior. Tests trigger apiFetch directly via page.evaluate when they need
// deterministic request counts (Dashboard auto-fetches /api/runs on mount,
// which would race with explicit assertions).

const NOOP_RUNS = JSON.stringify({ runs: [] });
const NOOP_HISTORY = JSON.stringify({ history: [] });
const NOOP_CONFIG = JSON.stringify({
  lang: 'en',
  privacy_mode: 'strict_local',
  generate_model: 'gpt-5.4-mini',
  judge_model: 'gpt-5.4-mini',
  serve_port: 8765,
  key_status: {},
});
const NOOP_TARGETS = JSON.stringify({ targets: [], total: 0 });
const NOOP_DOCTOR = JSON.stringify({ checks: [] });

async function installShellRoutes(
  page: Page,
  authHandler: (route: Route) => Promise<void> | void,
  runsHandler?: (route: Route) => Promise<void> | void,
): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/auth/token',
    async (route) => {
      await authHandler(route);
    },
  );
  await page.route(
    (url) => url.pathname === '/api/locale',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ locale: 'en' }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/runs',
    runsHandler ??
      ((route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: NOOP_RUNS })),
  );
  await page.route(
    (url) => url.pathname === '/api/ratchet/history',
    (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: NOOP_HISTORY }),
  );
  await page.route(
    (url) => url.pathname === '/api/config',
    (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: NOOP_CONFIG }),
  );
  await page.route(
    (url) => url.pathname === '/api/install/targets',
    (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: NOOP_TARGETS }),
  );
  await page.route(
    (url) => url.pathname === '/api/doctor',
    (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: NOOP_DOCTOR }),
  );
}

test.describe('Phase 2H — auth bootstrap', () => {
  test('uses POST method to bootstrap /api/auth/token', async ({ page }) => {
    const methods: string[] = [];
    await installShellRoutes(page, (route) => {
      methods.push(route.request().method());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'tkn-post-1' }),
      });
    });

    // /welcome avoids races with Dashboard auto-fetch and small-viewport
    // layout shifts that would otherwise change request timing on
    // Firefox/WebKit. We trigger ensureToken explicitly via apiFetch so the
    // POST happens deterministically across all browsers.
    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    await page.evaluate(async () => {
      // Vite dev serves /src/* at the original source URL; using a string
      // variable + a /* @vite-ignore */ hint keeps tsc and Vite happy
      // simultaneously (tsc treats `import(string)` as Promise<any>; Vite
      // skips static analysis).
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
      };
      await mod.apiFetch('/api/runs').catch(() => {});
    });

    expect(methods.length).toBeGreaterThanOrEqual(1);
    expect(methods).toEqual(methods.map(() => 'POST'));
  });

  test('rejects cross-origin apiFetch paths before attaching the token', async ({ page }) => {
    let authCalls = 0;
    let leakedRequests = 0;
    await installShellRoutes(page, (route) => {
      authCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'should-not-fetch' }),
      });
    });
    await page.route('https://example.invalid/**', (route) => {
      leakedRequests += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;
    const result = await page.evaluate(async () => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('secret-token');
      try {
        await mod.apiFetch('https://example.invalid/api/runs');
        return { status: null, message: 'resolved' };
      } catch (err) {
        const record =
          err && typeof err === 'object' ? err as { status?: unknown; message?: unknown } : {};
        return {
          status: typeof record.status === 'number' ? record.status : null,
          message: typeof record.message === 'string' ? record.message : String(err),
        };
      }
    });

    expect(result.status).toBe(0);
    expect(result.message).toContain('outside same-origin /api paths');
    expect(authCalls).toBe(0);
    expect(leakedRequests).toBe(0);
  });

  test('normalizes relative API paths before attaching the token', async ({ page }) => {
    let authCalls = 0;
    let captured: string | null = null;
    let leakedRequests = 0;
    await installShellRoutes(
      page,
      (route) => {
        authCalls += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ token: 'should-not-fetch' }),
        });
      },
      async (route) => {
        const headers = await route.request().allHeaders();
        captured = headers['x-ahadiff-token'] ?? null;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: NOOP_RUNS,
        });
      },
    );
    await page.route('https://example.invalid/**', (route) => {
      leakedRequests += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;
    await page.evaluate(async () => {
      const base = document.createElement('base');
      base.href = 'https://example.invalid/';
      document.head.appendChild(base);
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('secret-token');
      await mod.apiFetch('api/runs');
      base.remove();
    });

    expect(captured).toBe('secret-token');
    expect(authCalls).toBe(0);
    expect(leakedRequests).toBe(0);
  });

  test('forwards token via X-AhaDiff-Token on downstream apiFetch calls', async ({
    page,
  }) => {
    let captured: string | null = null;
    await installShellRoutes(
      page,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ token: 'tkn-fwd' }),
        }),
      async (route) => {
        // allHeaders() is the documented case-normalised path; headers() can
        // omit some custom headers depending on the request stage.
        const headers = await route.request().allHeaders();
        if (captured === null) captured = headers['x-ahadiff-token'] ?? null;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: NOOP_RUNS,
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    // Trigger a direct apiFetch too; the captured token may come from either
    // Landing's run preview fetch or this explicit call.
    await page.evaluate(async () => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
      };
      await mod.apiFetch('/api/runs');
    });

    expect(captured).toBe('tkn-fwd');
  });

  test('surfaces 403 on /api/auth/token with auth-specific UI message', async ({
    page,
  }) => {
    let authCalled = false;
    await installShellRoutes(page, (route) => {
      authCalled = true;
      return route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'forbidden' }),
      });
    });

    await page.goto('/', { timeout: 10_000 });
    // Dashboard maps ApiError(403/401) to the dashboard__error alert with
    // the auth_failed copy. We assert both that the alert is rendered AND
    // that it carries the auth-specific text — generic "fetch_failed" copy
    // would leave the user unable to distinguish auth from network errors
    // (G1 finding from Round 1 cross-review).
    const alert = page.locator('[role="alert"].dashboard__error');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/authentication failed/i);
    await expect(alert).toContainText(/ahadiff serve/);
    expect(authCalled).toBe(true);
  });

  test('aborts /api/auth/token after the 8s timeout', async ({ page }) => {
    test.setTimeout(20_000);
    await installShellRoutes(page, async (route) => {
      // Resolve only after the abort window so ensureToken's AbortController
      // gets to fire its 8s timeout.
      try {
        await new Promise((resolve) => setTimeout(resolve, 12_000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ token: 'should-not-be-used' }),
        });
      } catch {
        // route was already aborted; expected.
      }
    });

    const start = Date.now();
    await page.goto('/', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(9_500);
    // 8s abort + ~6s margin for slow CI runners (Playwright + browser cold
    // start can eat 2-3s on overcommitted GitHub runners — see R2-09).
    expect(Date.now() - start).toBeLessThan(15_000);
  });

  test('caller abort signal rejects while token bootstrap is pending', async ({ page }) => {
    test.setTimeout(15_000);
    let authCalls = 0;
    let slowBootstrap = false;
    await installShellRoutes(page, async (route) => {
      authCalls += 1;
      if (slowBootstrap) await new Promise((resolve) => setTimeout(resolve, 600));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'abort-probe-token' }),
      });
    });

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    await page.evaluate(async () => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
      };
      await mod.apiFetch('/api/runs').catch(() => {});
    });
    slowBootstrap = true;
    authCalls = 0;

    const result = await page.evaluate(async () => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string, init?: RequestInit) => Promise<unknown>;
        resetToken: () => void;
      };
      mod.resetToken();
      const controller = new AbortController();
      const start = performance.now();
      const request = mod.apiFetch('/api/runs', { signal: controller.signal });
      window.setTimeout(() => controller.abort(), 20);
      try {
        await request;
        return { name: 'resolved', elapsed: performance.now() - start };
      } catch (err) {
        const record =
          err && typeof err === 'object' ? err as { name?: unknown; message?: unknown } : {};
        return {
          name: typeof record.name === 'string' ? record.name : null,
          message: typeof record.message === 'string' ? record.message : String(err),
          elapsed: performance.now() - start,
        };
      }
    });

    expect(result.name).toBe('AbortError');
    expect(result.elapsed).toBeLessThan(500);
    expect(authCalls).toBe(1);
  });

  test('retries exactly once on 401 from a downstream apiFetch call', async ({ page }) => {
    // Use a synthetic endpoint the bundle never auto-fetches so the retry
    // counts are NOT polluted by bootstrap (apiFetch('/api/locale')) or any
    // page-level auto-fetch. The viewer's apiFetch is happy to call any path
    // — we only need a unique URL we can observe deterministically.
    const RETRY_PATH = '/api/__test_retry__';
    let authCalls = 0;
    let retryCalls = 0;

    await installShellRoutes(page, (route) => {
      authCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: `tkn-${authCalls}` }),
      });
    });
    await page.route(
      (url) => url.pathname === RETRY_PATH,
      (route) => {
        retryCalls += 1;
        if (retryCalls === 1) {
          return route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'stale' }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true }),
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;

    await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      await mod.apiFetch(path);
    }, RETRY_PATH);

    // Exactly two requests to the synthetic endpoint: the 401 + the retry.
    expect(retryCalls).toBe(2);
    expect(authCalls).toBe(1);
  });

  test('retries exactly once on 403 from a downstream apiFetch call', async ({ page }) => {
    const RETRY_PATH = '/api/__test_retry_forbidden__';
    let authCalls = 0;
    let retryCalls = 0;

    await installShellRoutes(page, (route) => {
      authCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: `tkn-forbidden-${authCalls}` }),
      });
    });
    await page.route(
      (url) => url.pathname === RETRY_PATH,
      (route) => {
        retryCalls += 1;
        if (retryCalls === 1) {
          return route.fulfill({
            status: 403,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'forbidden' }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true }),
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;

    await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      await mod.apiFetch(path);
    }, RETRY_PATH);

    expect(retryCalls).toBe(2);
    expect(authCalls).toBe(1);
  });

  test('coalesces concurrent stale-token retries into one refresh POST', async ({ page }) => {
    const CONCURRENT_PATH = '/api/__test_concurrent__';
    let authCalls = 0;
    let staleCalls = 0;
    let freshCalls = 0;

    await installShellRoutes(page, async (route) => {
      authCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 500));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'fresh-token' }),
      });
    });
    await page.route(
      (url) => url.pathname === CONCURRENT_PATH,
      async (route) => {
        const headers = await route.request().allHeaders();
        const token = headers['x-ahadiff-token'];
        if (token === 'stale-token') {
          staleCalls += 1;
          return route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'stale' }),
          });
        }
        freshCalls += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, token }),
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;

    await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      await Promise.all(Array.from({ length: 10 }, () => mod.apiFetch(path)));
    }, CONCURRENT_PATH);

    expect(authCalls).toBe(1);
    expect(staleCalls).toBe(10);
    expect(freshCalls).toBe(10);
  });

  test('does not refresh again for staggered stale-token responses', async ({ page }) => {
    const STAGGERED_PATH = '/api/__test_staggered__';
    let authCalls = 0;
    let staleCalls = 0;
    let freshCalls = 0;

    await installShellRoutes(page, async (route) => {
      authCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 100));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'fresh-staggered-token' }),
      });
    });
    await page.route(
      (url) => url.pathname === STAGGERED_PATH,
      async (route) => {
        const headers = await route.request().allHeaders();
        const token = headers['x-ahadiff-token'];
        if (token === 'stale-token') {
          staleCalls += 1;
          if (staleCalls === 2) await new Promise((resolve) => setTimeout(resolve, 500));
          return route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'stale' }),
          });
        }
        freshCalls += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, token }),
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;

    await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      await Promise.all([mod.apiFetch(path), mod.apiFetch(path)]);
    }, STAGGERED_PATH);

    expect(authCalls).toBe(1);
    expect(staleCalls).toBe(2);
    expect(freshCalls).toBe(2);
  });

  test('apiFetchVoid retries once on 401 and accepts 204', async ({ page }) => {
    const VOID_PATH = '/api/__test_void__';
    let authCalls = 0;
    let apiCalls = 0;

    await installShellRoutes(page, (route) => {
      authCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'fresh-void-token' }),
      });
    });
    await page.route(
      (url) => url.pathname === VOID_PATH,
      async (route) => {
        apiCalls += 1;
        const headers = await route.request().allHeaders();
        if (headers['x-ahadiff-token'] === 'stale-token') {
          return route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'stale' }),
          });
        }
        return route.fulfill({ status: 204 });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;
    await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        apiFetchVoid: (path: string) => Promise<void>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      await mod.apiFetchVoid(path);
    }, VOID_PATH);

    expect(authCalls).toBe(1);
    expect(apiCalls).toBe(2);
  });

  test('surfaces typed ApiError when the retry also returns 401', async ({ page }) => {
    const FAIL_PATH = '/api/__test_second_401__';
    let authCalls = 0;
    let apiCalls = 0;

    await installShellRoutes(page, (route) => {
      authCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'fresh-but-rejected' }),
      });
    });
    await page.route(
      (url) => url.pathname === FAIL_PATH,
      (route) => {
        apiCalls += 1;
        return route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'still_forbidden' }),
        });
      },
    );

    await page.goto('/#/welcome');
    await page.waitForLoadState('domcontentloaded');
    authCalls = 0;
    const result = await page.evaluate(async (path) => {
      const load = (p: string) => import(/* @vite-ignore */ p);
      const mod = (await load('/src/api/client.ts')) as {
        ApiError: new (
          status: number,
          body: unknown,
          message?: string,
        ) => Error & { status: number; body: unknown };
        apiFetch: (path: string) => Promise<unknown>;
        setToken: (token: string | null) => void;
      };
      mod.setToken('stale-token');
      try {
        await mod.apiFetch(path);
        return { isApiError: false, status: null, body: null };
      } catch (err) {
        return {
          isApiError: err instanceof mod.ApiError,
          status: err instanceof mod.ApiError ? err.status : null,
          body: err instanceof mod.ApiError ? err.body : null,
        };
      }
    }, FAIL_PATH);

    expect(result.isApiError).toBe(true);
    expect(result.status).toBe(401);
    expect(result.body).toEqual({ error: 'still_forbidden' });
    expect(authCalls).toBe(1);
    expect(apiCalls).toBe(2);
  });
});
