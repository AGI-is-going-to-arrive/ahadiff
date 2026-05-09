import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { improvePreflightResponseSchema, parseResponse } from './schemas';
import type { ImprovePreflightResponse } from './types';

export async function getImprovePreflight(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ImprovePreflightResponse> {
  const raw = await apiFetch<unknown>('/api/improve/preflight', opts);
  return parseResponse('GET /api/improve/preflight', improvePreflightResponseSchema, raw);
}
