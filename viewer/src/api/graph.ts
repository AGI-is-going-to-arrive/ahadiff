import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  conceptGraphResponseSchema,
  graphStatusResponseSchema,
  parseResponse,
} from './schemas';
import type { ConceptGraphResponse, GraphStatusResponse } from './types';

export async function fetchGraphStatus(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<GraphStatusResponse> {
  const raw = await apiFetch<unknown>('/api/graph/status', opts);
  return parseResponse('GET /api/graph/status', graphStatusResponseSchema, raw);
}

export async function fetchGraphConcepts(
  params: { limit?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConceptGraphResponse> {
  const q = new URLSearchParams();
  if (params.limit != null) q.set('limit', String(params.limit));
  const qs = q.toString();
  const raw = await apiFetch<unknown>(`/api/graph/concepts${qs ? `?${qs}` : ''}`, opts);
  return parseResponse('GET /api/graph/concepts', conceptGraphResponseSchema, raw);
}
