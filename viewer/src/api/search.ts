/**
 * Phase 4B: thin wrapper around `/api/search` for the SearchOverlay.
 * `/api/search` is gated behind same-origin token; everything else is
 * delegated to `apiFetch` so retry / 401 handling stays consistent.
 */
import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { parseResponse, searchResponseSchema } from './schemas';
import type { z } from 'zod';

export type SearchResponse = z.infer<typeof searchResponseSchema>;
export type SearchResult = SearchResponse['results'][number];

export async function searchAll(
  query: string,
  opts?: Pick<ApiFetchOptions, 'signal'> & { limit?: number; tables?: string },
): Promise<SearchResponse> {
  const q = new URLSearchParams({ q: query });
  if (opts?.limit != null) q.set('limit', String(opts.limit));
  if (opts?.tables) q.set('tables', opts.tables);
  const raw = await apiFetch<unknown>(`/api/search?${q.toString()}`, {
    signal: opts?.signal,
  });
  return parseResponse('GET /api/search', searchResponseSchema, raw);
}
