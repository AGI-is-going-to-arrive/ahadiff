/* `api/locale` is on the i18n bootstrap path (`i18n/bootstrap.ts` → `state/locale-store.ts` → here),
 * which means anything it imports lands in the shell entry chunk. To keep zod
 * out of the < 84 KB initial gzip budget we hand-roll the (tiny) type guard
 * here instead of going through `parseResponse(localeGetResponseSchema, …)`. */
import { apiFetch } from './client';
import type { LocaleGetResponse, LocalePutPayload } from './types';

class LocaleValidationError extends Error {
  override readonly name = 'ValidationError';
  constructor(public readonly endpoint: string, reason: string) {
    super(`Validation failed for ${endpoint}: ${reason}`);
  }
}

function ensureLocaleResponse(endpoint: string, raw: unknown): LocaleGetResponse {
  if (
    raw &&
    typeof raw === 'object' &&
    'locale' in raw &&
    (raw.locale === 'en' || raw.locale === 'zh-CN')
  ) {
    return { locale: raw.locale };
  }
  throw new LocaleValidationError(endpoint, 'expected { locale: "en" | "zh-CN" }');
}

export async function getLocale(): Promise<LocaleGetResponse> {
  const raw = await apiFetch<unknown>('/api/locale');
  return ensureLocaleResponse('GET /api/locale', raw);
}

export async function putLocale(payload: LocalePutPayload): Promise<LocaleGetResponse> {
  const raw = await apiFetch<unknown>('/api/locale', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return ensureLocaleResponse('PUT /api/locale', raw);
}
