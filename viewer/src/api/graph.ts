import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  conceptGraphResponseSchema,
  graphRefreshResponseSchema,
  graphStatusResponseSchema,
  parseResponse,
} from './schemas';
import type {
  ConceptGraphResponse,
  GraphRefreshResponse,
  GraphStatusResponse,
} from './types';

export async function fetchGraphStatus(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<GraphStatusResponse> {
  const raw = await apiFetch<unknown>('/api/graph/status', opts);
  return parseResponse('GET /api/graph/status', graphStatusResponseSchema, raw);
}

export async function fetchGraphConcepts(
  params: { limit?: number; focus?: string | null } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConceptGraphResponse> {
  const q = new URLSearchParams();
  if (params.limit != null) q.set('limit', String(params.limit));
  if (params.focus) q.set('focus', params.focus);
  const qs = q.toString();
  const raw = await apiFetch<unknown>(`/api/graph/concepts${qs ? `?${qs}` : ''}`, opts);
  return parseResponse('GET /api/graph/concepts', conceptGraphResponseSchema, raw);
}

export async function refreshGraph(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<GraphRefreshResponse> {
  const raw = await apiFetch<unknown>('/api/graph/refresh', {
    method: 'POST',
    ...opts,
  });
  return parseResponse('POST /api/graph/refresh', graphRefreshResponseSchema, raw);
}
