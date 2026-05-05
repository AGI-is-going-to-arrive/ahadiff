import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  parseResponse,
  taskCancelResponseSchema,
  taskInfoResponseSchema,
  taskListResponseSchema,
  taskSubmitResponseSchema,
} from './schemas';
import type {
  LearnEstimateResponse,
  LearnSubmitPayload,
  TaskCancelResponse,
  TaskInfoResponse,
  TaskListResponse,
  TaskSubmitResponse,
} from './types';

export async function estimateLearn(
  payload: LearnSubmitPayload = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<LearnEstimateResponse> {
  const raw = await apiFetch<LearnEstimateResponse>('/api/learn/estimate', {
    method: 'POST',
    body: JSON.stringify(payload),
    ...opts,
  });
  return raw;
}

export async function startLearnTask(
  payload: LearnSubmitPayload = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<TaskSubmitResponse> {
  const raw = await apiFetch<unknown>('/api/learn', {
    method: 'POST',
    body: JSON.stringify(payload),
    ...opts,
  });
  return parseResponse('POST /api/learn', taskSubmitResponseSchema, raw);
}

export async function listTasks(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<TaskListResponse> {
  const raw = await apiFetch<unknown>('/api/tasks', opts);
  return parseResponse('GET /api/tasks', taskListResponseSchema, raw);
}

export async function getTask(
  taskId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<TaskInfoResponse> {
  const raw = await apiFetch<unknown>(`/api/tasks/${encodeURIComponent(taskId)}`, opts);
  return parseResponse('GET /api/tasks/{taskId}', taskInfoResponseSchema, raw);
}

export async function cancelTask(
  taskId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<TaskCancelResponse> {
  const raw = await apiFetch<unknown>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
    ...opts,
  });
  return parseResponse('POST /api/tasks/{taskId}/cancel', taskCancelResponseSchema, raw);
}
