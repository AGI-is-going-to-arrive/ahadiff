import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { parseResponse, statsResponseSchema } from './schemas';
import type { StatsResponse } from './types';

export async function fetchStats(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<StatsResponse> {
  const raw = await apiFetch<unknown>('/api/stats', opts);
  return parseResponse('GET /api/stats', statsResponseSchema, raw);
}
