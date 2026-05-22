import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, apiFetchBlob, resetToken, setToken } from '../../src/api/client';
import { getConfig, putConfig } from '../../src/api/config';
import { ValidationError } from '../../src/api/schemas';

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

const TEST_ORIGIN = 'http://localhost:5173';

function apiUrl(path: string): string {
  return new URL(path, TEST_ORIGIN).href;
}

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
    vi.stubGlobal('window', { location: { origin: TEST_ORIGIN } });
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
        if (url === apiUrl('/api/auth/token')) {
          const pending = deferred<Response>();
          authResponses.push(pending);
          return pending.promise;
        }
        if (url === apiUrl('/api/runs')) {
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

  it('setToken cancels pending bootstrap state before injecting a manual token', async () => {
    const authResponses: Deferred<Response>[] = [];
    const runTokens: Array<string | null> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === apiUrl('/api/auth/token')) {
          const pending = deferred<Response>();
          authResponses.push(pending);
          return pending.promise;
        }
        if (url === apiUrl('/api/runs')) {
          runTokens.push(new Headers(init?.headers).get('x-ahadiff-token'));
          return Promise.resolve(jsonResponse({ runs: [] }));
        }
        return Promise.resolve(jsonResponse({ error: 'unexpected request', url }, 404));
      }),
    );

    const first = apiFetch<{ runs: unknown[] }>('/api/runs');
    await waitForPendingAuth(authResponses, 1);

    setToken('manual-token');
    await expect(apiFetch<{ runs: unknown[] }>('/api/runs')).resolves.toEqual({ runs: [] });

    authResponses[0].resolve(jsonResponse({ token: 'stale-bootstrap-token' }));
    await expect(first).resolves.toEqual({ runs: [] });

    await expect(apiFetch<{ runs: unknown[] }>('/api/runs')).resolves.toEqual({ runs: [] });
    expect(runTokens).toEqual([
      'manual-token',
      'stale-bootstrap-token',
      'manual-token',
    ]);
  });

  it('drops a pending refresh promise so post-reset retries fetch independently', async () => {
    const authResponses: Deferred<Response>[] = [];
    const runTokens: Array<string | null> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === apiUrl('/api/auth/token')) {
          const pending = deferred<Response>();
          authResponses.push(pending);
          return pending.promise;
        }
        if (url === apiUrl('/api/runs')) {
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

  it('drops prototype keys from sanitized API error bodies', () => {
    const payload = JSON.parse(
      '{"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}},"safe":1,"nested":{"prototype":"x","value":2}}',
    ) as unknown;

    const err = new ApiError(500, payload);
    expect(Object.getPrototypeOf(err.body)).toBe(Object.prototype);
    expect((err.body as Record<string, unknown>).safe).toBe(1);
    expect(Object.prototype.hasOwnProperty.call(err.body, '__proto__')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(err.body, 'constructor')).toBe(false);
    expect((err.body as Record<string, unknown>).nested).toEqual({ value: 2 });
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('derives Error.message from the sanitized body', () => {
    const err = new ApiError(500, {
      error: 'provider failed with sk-live-secret-token',
    });

    expect(err.message).toBe('[REDACTED]');
    expect(err.message).not.toContain('sk-live-secret-token');
  });
});

describe('auth bootstrap edge cases (Phase 2H)', () => {
  beforeEach(() => {
    resetToken();
    vi.stubGlobal('window', { location: { origin: TEST_ORIGIN } });
  });

  afterEach(() => {
    resetToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('surfaces 403 from bootstrap when same-origin gate rejects', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
      if (String(input) === apiUrl('/api/auth/token')) {
        return Promise.resolve(
          jsonResponse({ detail: 'same-origin required' }, 403),
        );
      }
      return Promise.resolve(jsonResponse({ runs: [] }));
    });
    vi.stubGlobal('fetch', fetchMock);

    const err = await apiFetch('/api/runs').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('aborts bootstrap after 8 s timeout', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
          new Promise<Response>((_resolve, reject) => {
            if (init?.signal?.aborted) {
              reject(new DOMException('The operation was aborted.', 'AbortError'));
              return;
            }
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted.', 'AbortError'));
            });
          }),
      ),
    );

    const promise = apiFetch<unknown>('/api/runs').catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(8001);
    const err = await promise;
    expect(err).toBeInstanceOf(DOMException);
  });

  it('propagates network errors from bootstrap without retry loop', async () => {
    const fetchMock = vi.fn((): Promise<Response> =>
      Promise.reject(new TypeError('Failed to fetch')),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/api/runs')).rejects.toThrow(TypeError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('rejects malformed bootstrap payloads without leaking token-like values', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        if (String(input) === apiUrl('/api/auth/token')) {
          return Promise.resolve(
            jsonResponse({ token: '', backup_token: 'sk-should-not-leak-token' }),
          );
        }
        return Promise.resolve(jsonResponse({ runs: [] }));
      }),
    );

    const err = await apiFetch('/api/runs').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).name).toBe('ValidationError');
    expect(String(err)).not.toContain('sk-should-not-leak-token');
    expect(JSON.stringify(err)).not.toContain('sk-should-not-leak-token');
  });

  it('retries once on 401 from data endpoint after successful bootstrap', async () => {
    let callCount = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        if (String(input) === apiUrl('/api/auth/token')) {
          return Promise.resolve(jsonResponse({ token: `tok-${++callCount}` }));
        }
        const token = callCount === 1 ? 'stale' : 'fresh';
        if (token === 'stale' && callCount <= 2) {
          return Promise.resolve(jsonResponse({ error: 'unauthorized' }, 401));
        }
        return Promise.resolve(jsonResponse({ runs: [] }));
      }),
    );

    await expect(apiFetch('/api/runs')).resolves.toEqual({ runs: [] });
  });
});

describe('config api', () => {
  beforeEach(() => {
    resetToken();
    setToken('unit-test-token');
    vi.stubGlobal('window', { location: { origin: TEST_ORIGIN } });
  });

  afterEach(() => {
    resetToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('parses quiz question count from GET /api/config', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            lang: 'en',
            privacy_mode: 'strict_local',
            generate_provider: null,
            generate_model: 'gpt-5.4-mini',
            judge_provider: null,
            judge_model: 'gpt-5.4-mini',
            serve_port: 8765,
            key_status: {},
            capture: {
              max_files: 30,
              hard_limit: 3000,
              max_patch_bytes: 5000000,
              file_ranking: 'learning_value',
              symbol_extractor: 'auto',
            },
            llm: {
              input_token_budget: 200000,
              output_token_budget: 50000,
              request_timeout_seconds: 30,
              max_concurrent: 3,
              retry_attempts: 3,
              output_lang: 'auto',
            },
            learn: {
              learnability_threshold: 0.3,
              desired_retention: 0.9,
            },
            quiz: {
              quiz_question_count: 6,
            },
          }),
        ),
      ),
    );

    await expect(getConfig()).resolves.toMatchObject({
      quiz: {
        quiz_question_count: 6,
        quiz_question_count_mode: 'fixed',
        quiz_auto_range_min: 3,
        quiz_auto_range_max: 12,
      },
    });
  });

  it('rejects GET /api/config payloads with quiz_question_count above max (31)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            lang: 'en',
            privacy_mode: 'strict_local',
            generate_provider: null,
            generate_model: 'gpt-5.4-mini',
            judge_provider: null,
            judge_model: 'gpt-5.4-mini',
            serve_port: 8765,
            key_status: {},
            capture: {
              max_files: 30,
              hard_limit: 3000,
              max_patch_bytes: 5000000,
              file_ranking: 'learning_value',
              symbol_extractor: 'auto',
            },
            llm: {
              input_token_budget: 200000,
              output_token_budget: 50000,
              request_timeout_seconds: 30,
              max_concurrent: 3,
              retry_attempts: 3,
              output_lang: 'auto',
            },
            learn: {
              learnability_threshold: 0.3,
              desired_retention: 0.9,
            },
            quiz: {
              quiz_question_count: 31,
              quiz_question_count_mode: 'fixed',
              quiz_auto_range_min: 3,
              quiz_auto_range_max: 12,
            },
          }),
        ),
      ),
    );

    await expect(getConfig()).rejects.toBeInstanceOf(ValidationError);
  });

  it('rejects GET /api/config payloads with quiz_auto_range_max above max (31)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            lang: 'en',
            privacy_mode: 'strict_local',
            generate_provider: null,
            generate_model: 'gpt-5.4-mini',
            judge_provider: null,
            judge_model: 'gpt-5.4-mini',
            serve_port: 8765,
            key_status: {},
            capture: {
              max_files: 30,
              hard_limit: 3000,
              max_patch_bytes: 5000000,
              file_ranking: 'learning_value',
              symbol_extractor: 'auto',
            },
            llm: {
              input_token_budget: 200000,
              output_token_budget: 50000,
              request_timeout_seconds: 30,
              max_concurrent: 3,
              retry_attempts: 3,
              output_lang: 'auto',
            },
            learn: {
              learnability_threshold: 0.3,
              desired_retention: 0.9,
            },
            quiz: {
              quiz_question_count: 3,
              quiz_question_count_mode: 'auto',
              quiz_auto_range_min: 3,
              quiz_auto_range_max: 31,
            },
          }),
        ),
      ),
    );

    await expect(getConfig()).rejects.toBeInstanceOf(ValidationError);
  });

  it('parses PUT /api/config update acknowledgements and sends JSON', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      expect(String(input)).toBe(apiUrl('/api/config'));
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

describe('api client blob downloads', () => {
  beforeEach(() => {
    resetToken();
    setToken('unit-test-token');
    vi.stubGlobal('window', { location: { origin: TEST_ORIGIN } });
  });

  afterEach(() => {
    resetToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fetches file exports with the write token header', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      expect(String(input)).toBe(apiUrl('/api/export/results?format=tsv'));
      const headers = new Headers(init?.headers);
      expect(headers.get('x-ahadiff-token')).toBe('unit-test-token');
      return Promise.resolve(
        new Response('timestamp\trun_id\n', {
          status: 200,
          headers: { 'content-type': 'text/tab-separated-values' },
        }),
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    const blob = await apiFetchBlob('/api/export/results?format=tsv');

    await expect(blob.text()).resolves.toBe('timestamp\trun_id\n');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
