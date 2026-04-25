import type { AuthTokenResponse } from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message?: string,
  ) {
    super(message ?? `API ${status}`);
  }
}

let cachedToken: string | null = null;
let tokenPromise: Promise<string> | null = null;

// Cap the auth-token bootstrap fetch so a stalled /api/auth/token endpoint
// can't deadlock every API call queued behind ensureToken().
const TOKEN_FETCH_TIMEOUT_MS = 8000;

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function clearToken(): void {
  cachedToken = null;
  tokenPromise = null;
}

async function ensureToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  if (tokenPromise) return tokenPromise;
  tokenPromise = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TOKEN_FETCH_TIMEOUT_MS);
    try {
      const res = await fetch('/api/auth/token', {
        credentials: 'same-origin',
        signal: controller.signal,
      });
      if (!res.ok)
        throw new ApiError(res.status, await safeJson(res), 'auth token fetch failed');
      const data = (await res.json()) as AuthTokenResponse;
      cachedToken = data.token;
      return cachedToken;
    } finally {
      clearTimeout(timer);
      tokenPromise = null;
    }
  })();
  return tokenPromise;
}

export function resetToken(): void {
  cachedToken = null;
}

export function setToken(token: string | null): void {
  cachedToken = token;
}

/**
 * Build headers and execute a single fetch with the given token.
 * Factored out so apiFetch / apiFetchVoid can retry once on 401/403.
 */
async function rawFetch(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set('X-AhaDiff-Token', token);
  if (init?.body && !headers.has('content-type'))
    headers.set('content-type', 'application/json');
  return fetch(path, { ...init, headers, credentials: 'same-origin' });
}

export type ApiFetchOptions = RequestInit;

export async function apiFetch<T>(path: string, init?: ApiFetchOptions): Promise<T> {
  let token = await ensureToken();
  let res = await rawFetch(path, token, init);

  // On 401/403 the cached token may be stale (e.g. serve process restarted).
  // Clear it, obtain a fresh one, and retry exactly once.
  if (res.status === 401 || res.status === 403) {
    clearToken();
    token = await ensureToken();
    res = await rawFetch(path, token, init);
  }

  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
  if (res.status === 204) {
    // Callers expecting T must use apiFetchVoid for void endpoints.
    throw new ApiError(204, null, `unexpected 204 No Content for ${path}; use apiFetchVoid`);
  }
  return (await res.json()) as T;
}

/** Variant for endpoints that may legitimately return 204 No Content. */
export async function apiFetchVoid(path: string, init?: RequestInit): Promise<void> {
  let token = await ensureToken();
  let res = await rawFetch(path, token, init);

  if (res.status === 401 || res.status === 403) {
    clearToken();
    token = await ensureToken();
    res = await rawFetch(path, token, init);
  }

  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
}
