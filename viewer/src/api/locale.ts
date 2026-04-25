import { apiFetch } from './client';
import type { LocaleGetResponse, LocalePutPayload } from './types';

export function getLocale(): Promise<LocaleGetResponse> {
  return apiFetch<LocaleGetResponse>('/api/locale');
}

export function putLocale(payload: LocalePutPayload): Promise<LocaleGetResponse> {
  return apiFetch<LocaleGetResponse>('/api/locale', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}
