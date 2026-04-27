import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import type {
  ReviewQueueResponse,
  ReviewRatePayload,
  ReviewRateResponse,
} from './types';

export async function getReviewQueue(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewQueueResponse> {
  return apiFetch<ReviewQueueResponse>('/api/review/queue', opts);
}

export async function submitReviewRate(
  payload: ReviewRatePayload,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ReviewRateResponse> {
  return apiFetch<ReviewRateResponse>('/api/review/rate', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal: opts?.signal,
  });
}
