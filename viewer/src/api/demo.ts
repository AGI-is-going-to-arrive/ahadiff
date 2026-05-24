import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { demoLearnPreviewResponseSchema, parseResponse } from './schemas';
import type { z } from 'zod';

export type DemoClaimPreview = z.infer<typeof demoLearnPreviewResponseSchema>['claims'][number];
export type DemoQuizPreview = z.infer<typeof demoLearnPreviewResponseSchema>['quiz'];
export type DemoLearnPreviewResponse = z.infer<typeof demoLearnPreviewResponseSchema>;

export async function getDemoLearnPreview(
  opts?: Pick<ApiFetchOptions, 'headers' | 'signal'>,
): Promise<DemoLearnPreviewResponse> {
  const raw = await apiFetch<unknown>('/api/demo/learn-preview', { ...opts, skipAuth: true });
  return parseResponse('GET /api/demo/learn-preview', demoLearnPreviewResponseSchema, raw);
}
