import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { heatmapResponseSchema, parseResponse, statsResponseSchema } from './schemas';
import type { ReviewHeatmapResponse, StatsResponse } from './types';

export async function fetchStats(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<StatsResponse> {
  const raw = await apiFetch<unknown>('/api/stats', opts);
  return parseResponse('GET /api/stats', statsResponseSchema, raw);
}

export async function fetchReviewHeatmap(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewHeatmapResponse> {
  const raw = await apiFetch<unknown>('/api/review/heatmap', opts);
  return parseResponse('GET /api/review/heatmap', heatmapResponseSchema, raw);
}
