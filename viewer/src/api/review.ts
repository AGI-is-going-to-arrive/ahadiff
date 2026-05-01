import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  parseResponse,
  reviewQueueResponseSchema,
  reviewQueueStateResponseSchema,
  reviewRateResponseSchema,
} from './schemas';
import type {
  ReviewQueueResponse,
  ReviewQueueStatePayload,
  ReviewQueueStateResponse,
  ReviewRatePayload,
  ReviewRateResponse,
} from './types';

export async function getReviewQueue(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewQueueResponse> {
  const raw = await apiFetch<unknown>('/api/review/queue', opts);
  return parseResponse('GET /api/review/queue', reviewQueueResponseSchema, raw);
}

export async function submitReviewRate(
  payload: ReviewRatePayload,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewRateResponse> {
  const raw = await apiFetch<unknown>('/api/review/rate', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal: opts?.signal,
  });
  return parseResponse('POST /api/review/rate', reviewRateResponseSchema, raw);
}

export async function updateReviewQueueState(
  payload: ReviewQueueStatePayload,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewQueueStateResponse> {
  const raw = await apiFetch<unknown>('/api/review/queue-state', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal: opts?.signal,
  });
  return parseResponse('POST /api/review/queue-state', reviewQueueStateResponseSchema, raw);
}
