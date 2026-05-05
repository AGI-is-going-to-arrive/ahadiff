import type { AuthTokenResponse } from './types';

const REDACTED = '[REDACTED]';
const SENSITIVE_KEY_RE = /(?:api[_-]?key|authorization|bearer|credential|password|secret|token)/i;
const SECRET_VALUE_RE =
  /\b(?:Bearer\s+)?(?:sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]*token[A-Za-z0-9_-]*)\b/i;
const UNSAFE_OBJECT_KEYS = new Set(['__proto__', 'prototype', 'constructor']);

function sanitizeApiErrorBody(body: unknown, depth = 0): unknown {
  if (depth > 8) return '[Truncated]';
  if (typeof body === 'string') {
    return SECRET_VALUE_RE.test(body) ? REDACTED : body;
  }
  if (Array.isArray(body)) {
    return body.map((item) => sanitizeApiErrorBody(item, depth + 1));
  }
  if (body && typeof body === 'object') {
    const sanitized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(body)) {
      if (UNSAFE_OBJECT_KEYS.has(key)) continue;
      sanitized[key] = SENSITIVE_KEY_RE.test(key)
        ? REDACTED
        : sanitizeApiErrorBody(value, depth + 1);
    }
    return sanitized;
  }
  return body;
}

function extractApiErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'error' in body) {
    const error = (body as Record<string, unknown>).error;
    if (typeof error === 'string') return error;
  }
  return `API ${status}`;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(
    status: number,
    body: unknown,
    message?: string,
  ) {
    super(message ?? extractApiErrorMessage(body, status));
    this.status = status;
    this.body = sanitizeApiErrorBody(body);
  }
}

let cachedToken: string | null = null;
let tokenPromise: Promise<string> | null = null;
// Coalesces the 401/403 retry path so N concurrent stale-token failures
// produce ONE refresh fetch instead of N (CR1-01 thundering-herd fix).
let refreshPromise: Promise<string> | null = null;
let tokenGeneration = 0;
let tokenRequestId = 0;
let refreshRequestId = 0;

// Cap the auth-token bootstrap fetch so a stalled /api/auth/token endpoint
// can't deadlock every API call queued behind ensureToken().
const TOKEN_FETCH_TIMEOUT_MS = 8000;

function normalizeApiPath(path: string): string {
  let url: URL;
  try {
    url = new URL(path, window.location.origin);
  } catch {
    throw new ApiError(0, { error: 'invalid_api_path', path }, 'invalid API path');
  }
  const isApiPath = url.pathname === '/api' || url.pathname.startsWith('/api/');
  if (url.origin !== window.location.origin || !isApiPath) {
    throw new ApiError(
      0,
      { error: 'invalid_api_path', path },
      'refusing to send API token outside same-origin /api paths',
    );
  }
  return `${url.pathname}${url.search}`;
}

function abortError(signal: AbortSignal): Error {
  if (signal.reason instanceof Error) return signal.reason;
  return new DOMException('The operation was aborted.', 'AbortError');
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError(signal);
}

function withAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  throwIfAborted(signal);
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError(signal));
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (err: unknown) => {
        signal.removeEventListener('abort', onAbort);
        reject(err);
      },
    );
  });
}

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

class AuthTokenValidationError extends Error {
  override readonly name = 'ValidationError';

  constructor(public readonly endpoint: string) {
    super(`Validation failed for ${endpoint}: token(invalid_type)`);
  }
}

function ensureAuthTokenResponse(raw: unknown): AuthTokenResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new AuthTokenValidationError('POST /api/auth/token');
  }
  const record = raw as Record<string, unknown>;
  const allowed = new Set(['token', 'expires_at']);
  if (Object.keys(record).some((key) => !allowed.has(key))) {
    throw new AuthTokenValidationError('POST /api/auth/token');
  }
  const token = record.token;
  const expiresAt = record.expires_at;
  if (typeof token !== 'string' || token.length === 0) {
    throw new AuthTokenValidationError('POST /api/auth/token');
  }
  if (
    expiresAt !== undefined &&
    expiresAt !== null &&
    typeof expiresAt !== 'string'
  ) {
    throw new AuthTokenValidationError('POST /api/auth/token');
  }
  return { token, expires_at: expiresAt ?? undefined };
}

function clearToken(): void {
  cachedToken = null;
  tokenPromise = null;
  tokenRequestId += 1;
}

// Single-flight refresh: if N apiFetch calls all hit 401/403, only the
// first triggers clearToken + ensureToken; the rest await the same promise.
function refreshToken(failedToken: string, signal?: AbortSignal): Promise<string> {
  throwIfAborted(signal);
  if (cachedToken && cachedToken !== failedToken) return Promise.resolve(cachedToken);
  if (refreshPromise) return withAbort(refreshPromise, signal);
  const requestId = ++refreshRequestId;
  refreshPromise = (async () => {
    try {
      if (!cachedToken || cachedToken === failedToken) clearToken();
      return await ensureToken();
    } finally {
      if (refreshRequestId === requestId) refreshPromise = null;
    }
  })();
  return withAbort(refreshPromise, signal);
}

async function ensureToken(signal?: AbortSignal): Promise<string> {
  throwIfAborted(signal);
  if (cachedToken) return cachedToken;
  if (tokenPromise) return withAbort(tokenPromise, signal);
  const generation = tokenGeneration;
  const requestId = ++tokenRequestId;
  tokenPromise = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TOKEN_FETCH_TIMEOUT_MS);
    try {
      // Phase 2H: default to POST /api/auth/token (same-origin bootstrap gate).
      // GET remains backend-only compatibility for non-browser callers; the
      // viewer never falls back to GET here — see plan §2H and BF-5.
      const res = await fetch('/api/auth/token', {
        method: 'POST',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      if (!res.ok)
        throw new ApiError(res.status, await safeJson(res), 'auth token fetch failed');
      const data = ensureAuthTokenResponse(await safeJson(res));
      if (generation === tokenGeneration && tokenRequestId === requestId) {
        cachedToken = data.token;
      }
      return data.token;
    } finally {
      clearTimeout(timer);
      if (tokenRequestId === requestId) tokenPromise = null;
    }
  })();
  return withAbort(tokenPromise, signal);
}

export function resetToken(): void {
  tokenGeneration += 1;
  refreshRequestId += 1;
  clearToken();
  refreshPromise = null;
}

export function setToken(token: string | null): void {
  cachedToken = token;
}

/**
 * Build headers and execute a single fetch with the given token.
 * Factored out so apiFetch / apiFetchVoid can retry once on 401/403.
 */
async function rawFetch(
  apiPath: string,
  token: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set('X-AhaDiff-Token', token);
  if (init?.body && !headers.has('content-type'))
    headers.set('content-type', 'application/json');
  return fetch(apiPath, { ...init, headers, credentials: 'same-origin' });
}

export type ApiFetchOptions = RequestInit;

export async function apiFetch<T>(path: string, init?: ApiFetchOptions): Promise<T> {
  const apiPath = normalizeApiPath(path);
  const signal = init?.signal ?? undefined;
  let token = await ensureToken(signal);
  let res = await rawFetch(apiPath, token, init);

  // On 401/403 the cached token may be stale (e.g. serve process restarted).
  // refreshToken() coalesces concurrent refreshes so one stale-token storm
  // produces a single POST /api/auth/token, not N (CR1-01).
  if (res.status === 401 || res.status === 403) {
    token = await refreshToken(token, signal);
    res = await rawFetch(apiPath, token, init);
  }

  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
  if (res.status === 204) {
    // Callers expecting T must use apiFetchVoid for void endpoints.
    throw new ApiError(204, null, `unexpected 204 No Content for ${apiPath}; use apiFetchVoid`);
  }
  return (await res.json()) as T;
}

/** Variant for endpoints that may legitimately return 204 No Content. */
export async function apiFetchVoid(path: string, init?: RequestInit): Promise<void> {
  const apiPath = normalizeApiPath(path);
  const signal = init?.signal ?? undefined;
  let token = await ensureToken(signal);
  let res = await rawFetch(apiPath, token, init);

  if (res.status === 401 || res.status === 403) {
    token = await refreshToken(token, signal);
    res = await rawFetch(apiPath, token, init);
  }

  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
}
