import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  learnEstimateResponseSchema,
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
  onTransientError?: () => void;
}

export async function estimateLearn(
  payload: LearnSubmitPayload = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<LearnEstimateResponse> {
  const raw = await apiFetch<unknown>('/api/learn/estimate', {
    method: 'POST',
    body: JSON.stringify(payload),
    ...opts,
  });
  return parseResponse('POST /api/learn/estimate', learnEstimateResponseSchema, raw);
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

const SSE_MAX_RETRIES = 5;
const SSE_BASE_DELAY_MS = 1000;

export function subscribeTaskProgress(
  taskId: string,
  handlers: TaskProgressHandlers,
): TaskProgressSubscription | null {
  if (typeof EventSource === 'undefined') return null;

  let closed = false;
  let retries = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let source: EventSource | null = null;

  const close = () => {
    if (closed) return;
    closed = true;
    if (retryTimer !== null) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    source?.close();
    source = null;
  };

  function connect() {
    if (closed) return;
    retryTimer = null;
    source?.close();
    const es = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/progress`);
    source = es;

    es.addEventListener('progress', (event) => {
      if (closed || source !== es) return;
      try {
        const payload = parseTaskProgressEvent((event as MessageEvent<string>).data);
        if (payload.event !== 'progress') throw new Error('unexpected_task_progress_event');
        retries = 0;
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

    es.addEventListener('error', (event) => {
      if (closed || source !== es) return;
      const hasData = 'data' in event && typeof event.data === 'string' && event.data !== '';
      if (hasData) {
        let error = new Error('task_progress_stream_error');
        try {
          const payload = parseTaskProgressEvent(event.data as string);
          if (payload.event === 'error') error = new Error(payload.data.error);
        } catch (err: unknown) {
          error = errorFromUnknown(err);
        }
        close();
        handlers.onError(error);
        return;
      }
      // Transient network error — notify caller immediately so it can
      // start polling fallback, then retry SSE in the background.
      es.close();
      source = null;
      if (retries === 0) {
        handlers.onTransientError?.();
      }
      if (retries >= SSE_MAX_RETRIES) {
        close();
        handlers.onError(new Error('task_progress_stream_error'));
        return;
      }
      const delay = SSE_BASE_DELAY_MS * Math.pow(2, retries);
      retries += 1;
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, delay);
    });
  }

  connect();
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
