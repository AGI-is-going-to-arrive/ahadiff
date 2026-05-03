import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  heatmapResponseSchema,
  learningEffectivenessResponseSchema,
  parseResponse,
  serveStatusResponseSchema,
  specAlignmentResponseSchema,
  statsResponseSchema,
  watchStatusResponseSchema,
} from './schemas';
import type {
  LearningEffectivenessResponse,
  ReviewHeatmapResponse,
  ServeStatusResponse,
  SpecAlignmentResponse,
  StatsResponse,
  WatchStatusResponse,
} from './types';

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

export async function fetchServeStatus(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ServeStatusResponse> {
  const raw = await apiFetch<unknown>('/api/serve/status', opts);
  return parseResponse('GET /api/serve/status', serveStatusResponseSchema, raw);
}

export async function fetchLearningEffectiveness(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<LearningEffectivenessResponse> {
  const raw = await apiFetch<unknown>('/api/stats/learning', opts);
  return parseResponse('GET /api/stats/learning', learningEffectivenessResponseSchema, raw);
}

export async function fetchSpecAlignment(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<SpecAlignmentResponse> {
  const raw = await apiFetch<unknown>('/api/spec/alignment', opts);
  return parseResponse('GET /api/spec/alignment', specAlignmentResponseSchema, raw);
}

export async function fetchWatchStatus(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<WatchStatusResponse> {
  const raw = await apiFetch<unknown>('/api/watch/status', opts);
  return parseResponse('GET /api/watch/status', watchStatusResponseSchema, raw);
}
