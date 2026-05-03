import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  parseResponse,
  reviewMasteryResponseSchema,
  reviewQueueResponseSchema,
  reviewQueueStateResponseSchema,
  reviewRateResponseSchema,
  weakConceptsResponseSchema,
} from './schemas';
import type {
  ReviewMasteryResponse,
  ReviewQueueResponse,
  ReviewQueueStatePayload,
  ReviewQueueStateResponse,
  ReviewRatePayload,
  ReviewRateResponse,
  WeakConceptsResponse,
} from './types';

export async function getReviewQueue(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewQueueResponse> {
  const raw = await apiFetch<unknown>('/api/review/queue', opts);
  return parseResponse('GET /api/review/queue', reviewQueueResponseSchema, raw);
}

export async function getWeakConcepts(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<WeakConceptsResponse> {
  const raw = await apiFetch<unknown>('/api/concepts/weak', opts);
  return parseResponse('GET /api/concepts/weak', weakConceptsResponseSchema, raw);
}

export async function getReviewMastery(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewMasteryResponse> {
  const raw = await apiFetch<unknown>('/api/review/mastery', opts);
  return parseResponse('GET /api/review/mastery', reviewMasteryResponseSchema, raw);
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
