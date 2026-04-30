import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, resetToken, setToken } from '../../src/api/client';
import { putConfig } from '../../src/api/config';
import { ValidationError } from '../../src/api/schemas';

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

async function waitForPendingAuth(authResponses: Deferred<Response>[], count: number): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (authResponses.length === count) return;
    await Promise.resolve();
  }
  expect(authResponses).toHaveLength(count);
}

describe('api client token reset', () => {
  beforeEach(() => {
    resetToken();
    vi.stubGlobal('window', { location: { origin: 'http://localhost:5173' } });
  });

  afterEach(() => {
    resetToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('drops a pending bootstrap token promise and does not recache its stale result', async () => {
    const authResponses: Deferred<Response>[] = [];
    const runTokens: Array<string | null> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/auth/token') {
          const pending = deferred<Response>();
          authResponses.push(pending);
          return pending.promise;
        }
        if (url === '/api/runs') {
          runTokens.push(new Headers(init?.headers).get('x-ahadiff-token'));
          return Promise.resolve(jsonResponse({ runs: [] }));
        }
        return Promise.resolve(jsonResponse({ error: 'unexpected request', url }, 404));
      }),
    );

    const first = apiFetch<{ runs: unknown[] }>('/api/runs');
    await waitForPendingAuth(authResponses, 1);

    resetToken();
    const second = apiFetch<{ runs: unknown[] }>('/api/runs');
    await waitForPendingAuth(authResponses, 2);

    authResponses[1].resolve(jsonResponse({ token: 'fresh-after-reset' }));
    await expect(second).resolves.toEqual({ runs: [] });

    authResponses[0].resolve(jsonResponse({ token: 'stale-before-reset' }));
    await expect(first).resolves.toEqual({ runs: [] });

    await apiFetch<{ runs: unknown[] }>('/api/runs');
    expect(runTokens).toEqual([
      'fresh-after-reset',
      'stale-before-reset',
      'fresh-after-reset',
    ]);
  });

  it('drops a pending refresh promise so post-reset retries fetch independently', async () => {
    const authResponses: Deferred<Response>[] = [];
    const runTokens: Array<string | null> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/auth/token') {
          const pending = deferred<Response>();
          authResponses.push(pending);
          return pending.promise;
        }
        if (url === '/api/runs') {
          const token = new Headers(init?.headers).get('x-ahadiff-token');
          runTokens.push(token);
          if (token?.startsWith('stale-')) {
            return Promise.resolve(jsonResponse({ error: 'stale' }, 401));
          }
          return Promise.resolve(jsonResponse({ runs: [] }));
        }
        return Promise.resolve(jsonResponse({ error: 'unexpected request', url }, 404));
      }),
    );

    setToken('stale-before-reset');
    const first = apiFetch<{ runs: unknown[] }>('/api/runs');
    await waitForPendingAuth(authResponses, 1);

    resetToken();
    setToken('stale-after-reset');
    const second = apiFetch<{ runs: unknown[] }>('/api/runs');
    await waitForPendingAuth(authResponses, 2);

    authResponses[1].resolve(jsonResponse({ token: 'fresh-after-reset' }));
    await expect(second).resolves.toEqual({ runs: [] });

    authResponses[0].resolve(jsonResponse({ token: 'fresh-before-reset' }));
    await expect(first).resolves.toEqual({ runs: [] });

    await apiFetch<{ runs: unknown[] }>('/api/runs');
    expect(runTokens).toEqual([
      'stale-before-reset',
      'stale-after-reset',
      'fresh-after-reset',
      'fresh-before-reset',
      'fresh-after-reset',
    ]);
  });
});

describe('ApiError redaction', () => {
  it('stores a sanitized body so accidental console logging cannot leak tokens', () => {
    const err = new ApiError(500, {
      error: 'provider_failed',
      api_key: 'sk-test-secret-token',
      nested: {
        Authorization: 'Bearer should-not-leak',
        detail: 'plain failure detail',
      },
    });

    expect(err.body).toEqual({
      error: 'provider_failed',
      api_key: '[REDACTED]',
      nested: {
        Authorization: '[REDACTED]',
        detail: 'plain failure detail',
      },
    });
    expect(JSON.stringify(err)).not.toContain('should-not-leak');
    expect(JSON.stringify(err.body)).not.toContain('sk-test-secret-token');
  });
});

describe('config api', () => {
  beforeEach(() => {
    resetToken();
    setToken('unit-test-token');
    vi.stubGlobal('window', { location: { origin: 'http://localhost:5173' } });
  });

  afterEach(() => {
    resetToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('parses PUT /api/config update acknowledgements and sends JSON', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      expect(String(input)).toBe('/api/config');
      expect(init?.method).toBe('PUT');
      expect(init?.body).toBe(JSON.stringify({ lang: 'zh-CN' }));
      const headers = new Headers(init?.headers);
      expect(headers.get('content-type')).toBe('application/json');
      expect(headers.get('x-ahadiff-token')).toBe('unit-test-token');
      return Promise.resolve(jsonResponse({ updated: true, scope: 'session' }));
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(putConfig({ lang: 'zh-CN' })).resolves.toEqual({
      updated: true,
      scope: 'session',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('rejects stale PUT /api/config payloads shaped like GET /api/config', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            lang: 'zh-CN',
            privacy_mode: 'strict_local',
            generate_model: null,
            judge_model: null,
            serve_port: 8384,
            key_status: {},
          }),
        ),
      ),
    );

    await expect(putConfig({ lang: 'zh-CN' })).rejects.toBeInstanceOf(ValidationError);
  });
});
