import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  parseResponse,
  taskCancelResponseSchema,
  taskInfoResponseSchema,
  taskListResponseSchema,
  taskProgressEventSchema,
  taskSubmitResponseSchema,
} from './schemas';
import type {
  LearnEstimateResponse,
  LearnSubmitPayload,
  TaskCancelResponse,
  TaskInfoResponse,
  TaskListResponse,
  TaskProgressEvent,
  TaskSubmitResponse,
} from './types';

export interface TaskProgressSubscription {
  close: () => void;
}

export interface TaskProgressHandlers {
  onProgress: (info: TaskInfoResponse) => void;
  onError: (error: Error) => void;
}

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

function errorFromUnknown(err: unknown): Error {
  return err instanceof Error ? err : new Error('task_progress_stream_error');
}

function parseTaskProgressEvent(rawData: string): TaskProgressEvent {
  return parseResponse(
    'GET /api/tasks/{taskId}/progress',
    taskProgressEventSchema,
    JSON.parse(rawData),
  );
}

export function subscribeTaskProgress(
  taskId: string,
  handlers: TaskProgressHandlers,
): TaskProgressSubscription | null {
  if (typeof EventSource === 'undefined') return null;
  const source = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/progress`);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    source.close();
  };

  source.addEventListener('progress', (event) => {
    if (closed) return;
    try {
      const payload = parseTaskProgressEvent((event as MessageEvent<string>).data);
      if (payload.event !== 'progress') throw new Error('unexpected_task_progress_event');
      handlers.onProgress(payload.data);
      if (
        payload.data.status === 'completed' ||
        payload.data.status === 'failed' ||
        payload.data.status === 'cancelled'
      ) {
        close();
      }
    } catch (err: unknown) {
      close();
      handlers.onError(errorFromUnknown(err));
    }
  });

  source.addEventListener('error', (event) => {
    if (closed) return;
    let error = new Error('task_progress_stream_error');
    try {
      const rawData = 'data' in event && typeof event.data === 'string' ? event.data : '';
      if (rawData) {
        const payload = parseTaskProgressEvent(rawData);
        if (payload.event === 'error') error = new Error(payload.data.error);
      }
    } catch (err: unknown) {
      error = errorFromUnknown(err);
    }
    close();
    handlers.onError(error);
  });

  return { close };
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
