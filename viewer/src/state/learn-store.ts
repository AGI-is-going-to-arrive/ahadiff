import { create } from 'zustand';
import {
  startLearnTask,
  estimateLearn,
  getTask,
  cancelTask,
  listTasks,
  subscribeTaskProgress,
} from '../api/tasks';
import { ApiError } from '../api/client';
import { useRunsStore } from './runs-store';
import { useGraphStore } from './graph-store';
import type { TaskInfoResponse, LearnSubmitPayload, LearnEstimateResponse } from '../api/types';
import type { TaskProgressSubscription } from '../api/tasks';

type LearnPhase =
  | 'idle'
  | 'estimating'
  | 'confirming'
  | 'submitting'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'cancelling';

interface LearnRequestOptions {
  signal?: AbortSignal;
}

const POLL_INTERVAL_MS = 1500;
const MAX_POLL_INTERVAL_MS = 30_000;
/**
 * Maximum number of consecutive polling errors before we surface an error
 * to the user. With exponential backoff (1500, 3000, 6000, 12000, 24000,
 * 30000, 30000, 30000, 30000, 30000) this corresponds to roughly 2.5
 * minutes of unrecoverable backend connectivity issues. Below this
 * threshold we keep retrying silently with backoff, since transient 5xx /
 * network blips are normal during long-running learn tasks.
 */
const MAX_CONSECUTIVE_POLL_ERRORS = 10;

/**
 * NOTE: We deliberately do NOT track a frontend-side polling deadline.
 *
 * Source-of-truth for task timeout is the backend `task_runner` (currently
 * 1800s). The backend exposes `timeout_seconds` + `deadline_at` on
 * `TaskInfoResponse`; the UI may use those fields for display only.
 *
 * Previously we forced phase=failed after 660s of local polling, which
 * triggered before the backend gave up — users saw "Learn run timed out"
 * while the task was still running on the server. The fix is to keep polling
 * as long as the backend reports running/pending, and only treat
 * completed/failed/cancelled (driven by the backend) as terminal.
 *
 * However we DO surface an error after MAX_CONSECUTIVE_POLL_ERRORS
 * consecutive failures so users aren't left staring at a silent spinner
 * when the backend is unreachable. The task may still be running on the
 * server side; the UI message reflects that and offers a retry that
 * reconnects polling.
 */

let pollTimer: ReturnType<typeof setTimeout> | null = null;
let progressSubscription: TaskProgressSubscription | null = null;
let submitGeneration = 0;
let consecutiveErrors = 0;
let pendingSubmitPayload: LearnSubmitPayload | null = null;

interface LearnState {
  phase: LearnPhase;
  taskId: string | null;
  task: TaskInfoResponse | null;
  estimate: LearnEstimateResponse | null;
  error: string | null;
  errorCode: string | null;
  lastPayload: LearnSubmitPayload | null;
  pendingPayload: LearnSubmitPayload | null;
  retryable: boolean;

  requestLearn: (payload?: LearnSubmitPayload, opts?: LearnRequestOptions) => Promise<void>;
  confirmLearn: () => Promise<void>;
  submitLearn: (payload?: LearnSubmitPayload) => Promise<void>;
  retryLearn: () => Promise<void>;
  cancelLearn: () => Promise<void>;
  dismiss: () => void;
  recoverExistingTask: () => Promise<void>;
  reconnectPoll: () => void;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function stopProgressSubscription(): void {
  progressSubscription?.close();
  progressSubscription = null;
}

function resetPollState(): void {
  stopPolling();
  stopProgressSubscription();
  consecutiveErrors = 0;
}

function stripSensitivePayload(payload: LearnSubmitPayload): LearnSubmitPayload {
  const { patch: _p, patch_url: _u, ...safePayload } = payload;
  return safePayload;
}

function isAbortError(err: unknown): boolean {
  return (
    typeof err === 'object'
    && err !== null
    && 'name' in err
    && (err as { name?: unknown }).name === 'AbortError'
  );
}

function nextPollIntervalMs(): number {
  return consecutiveErrors === 0
    ? POLL_INTERVAL_MS
    : Math.min(POLL_INTERVAL_MS * 2 ** consecutiveErrors, MAX_POLL_INTERVAL_MS);
}

function schedulePoll(delayMs = nextPollIntervalMs()): void {
  stopPolling();
  pollTimer = setTimeout(() => void doPoll(), delayMs);
}

function retryAfterDelayMs(err: ApiError): number | null {
  const body = err.body;
  const retryAfter = body && typeof body === 'object' && !Array.isArray(body)
    ? (body as Record<string, unknown>).retry_after
    : undefined;
  if (typeof retryAfter === 'number' && Number.isFinite(retryAfter) && retryAfter > 0) {
    return retryAfter * 1000;
  }
  if (typeof retryAfter === 'string' && retryAfter.trim() !== '') {
    const parsed = Number(retryAfter);
    if (Number.isFinite(parsed) && parsed > 0) return parsed * 1000;
  }
  return null;
}

function applyTaskInfo(capturedTaskId: string, info: TaskInfoResponse): boolean {
  const current = useLearnStore.getState();
  if (
    current.taskId !== capturedTaskId ||
    (current.phase !== 'running' && current.phase !== 'cancelling')
  ) {
    return true;
  }
  consecutiveErrors = 0;
  const s = info.status;
  if (s === 'completed') {
    useLearnStore.setState({ phase: 'completed', task: info });
    useRunsStore.setState({ lastLoadedAt: null });
    useGraphStore.getState().invalidate();
    resetPollState();
    return true;
  }
  if (s === 'cancelled') {
    useLearnStore.setState({ phase: 'cancelled', task: info });
    resetPollState();
    return true;
  }
  if (s === 'failed') {
    const retryAllowedByTask = (info.recovery_hint ?? 'retry') === 'retry';
    useLearnStore.setState({
      phase: 'failed',
      task: info,
      error: info.error,
      errorCode: info.error_code ?? 'internal_error',
      retryable: useLearnStore.getState().retryable && retryAllowedByTask,
    });
    resetPollState();
    return true;
  }
  useLearnStore.setState({ task: info });
  return false;
}

function startProgressTracking(taskId: string): void {
  resetPollState();
  try {
    progressSubscription = subscribeTaskProgress(taskId, {
      onProgress: (info) => {
        stopPolling();
        applyTaskInfo(taskId, info);
      },
      onError: () => {
        const current = useLearnStore.getState();
        if (
          current.taskId !== taskId ||
          (current.phase !== 'running' && current.phase !== 'cancelling')
        ) {
          return;
        }
        stopProgressSubscription();
        schedulePoll();
      },
      onTransientError: () => {
        const current = useLearnStore.getState();
        if (
          current.taskId !== taskId ||
          (current.phase !== 'running' && current.phase !== 'cancelling')
        ) {
          return;
        }
        schedulePoll();
      },
    });
  } catch {
    progressSubscription = null;
  }
  if (progressSubscription === null) schedulePoll();
}

async function doPoll(): Promise<void> {
  const state = useLearnStore.getState();
  const { taskId, phase } = state;
  if (!taskId || (phase !== 'running' && phase !== 'cancelling')) {
    resetPollState();
    return;
  }
  const capturedTaskId = taskId;
  try {
    const info = await getTask(capturedTaskId);
    if (!applyTaskInfo(capturedTaskId, info)) {
      schedulePoll();
    }
  } catch (err: unknown) {
    const current = useLearnStore.getState();
    if (current.taskId !== capturedTaskId || (current.phase !== 'running' && current.phase !== 'cancelling')) return;
    if (err instanceof ApiError) {
      if (err.status === 401 || err.status === 403) {
        useLearnStore.setState({
          phase: 'failed',
          error: null,
          errorCode: err.errorCode ?? 'poll_auth_error',
          retryable: false,
        });
        resetPollState();
        return;
      }
      if (err.status === 404) {
        useLearnStore.setState({
          phase: 'failed',
          error: null,
          errorCode: err.errorCode ?? 'poll_task_not_found',
          retryable: false,
        });
        resetPollState();
        return;
      }
      if (err.status === 429) {
        const retryAfterMs = retryAfterDelayMs(err);
        schedulePoll(Math.max(retryAfterMs ?? MAX_POLL_INTERVAL_MS, nextPollIntervalMs()));
        return;
      }
    }
    consecutiveErrors += 1;
    if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
      // Distinguish API errors (backend reachable but returned retryable 5xx) from
      // network failures (backend unreachable). Both surface the same
      // banner copy but differ in error code so logs / tests can tell.
      const isApiError = err instanceof ApiError;
      useLearnStore.setState({
        phase: 'failed',
        error: 'poll_connection_lost',
        errorCode: isApiError ? 'poll_server_error' : 'poll_connection_lost',
        retryable: true,
      });
      resetPollState();
      return;
    }
    schedulePoll();
  }
}

export const useLearnStore = create<LearnState>(() => ({
  phase: 'idle',
  taskId: null,
  task: null,
  estimate: null,
  error: null,
  errorCode: null,
  lastPayload: null,
  pendingPayload: null,
  retryable: true,

  requestLearn: async (payload, opts) => {
    const { phase } = useLearnStore.getState();
    if (phase === 'submitting' || phase === 'running' || phase === 'cancelling' || phase === 'estimating' || phase === 'confirming') return;
    const generation = ++submitGeneration;
    const effectivePayload = payload ?? {};
    const safePayload = stripSensitivePayload(effectivePayload);
    const retryable = effectivePayload.patch === undefined && effectivePayload.patch_url === undefined;
    pendingSubmitPayload = effectivePayload;
    useLearnStore.setState({
      phase: 'estimating',
      error: null,
      errorCode: null,
      task: null,
      taskId: null,
      estimate: null,
      lastPayload: safePayload,
      pendingPayload: safePayload,
      retryable,
    });
    try {
      const est = await estimateLearn(effectivePayload, opts);
      if (submitGeneration !== generation) return;
      if (est.risk_level === 'ok') {
        useLearnStore.setState({ estimate: est });
        await useLearnStore.getState().submitLearn(effectivePayload);
      } else {
        useLearnStore.setState({ phase: 'confirming', estimate: est });
      }
    } catch (err: unknown) {
      if (submitGeneration !== generation) return;
      if (opts?.signal?.aborted || isAbortError(err)) {
        pendingSubmitPayload = null;
        useLearnStore.setState({
          phase: 'idle',
          error: null,
          errorCode: null,
          task: null,
          taskId: null,
          estimate: null,
          pendingPayload: null,
        });
        return;
      }
      await useLearnStore.getState().submitLearn(effectivePayload);
    }
  },

  confirmLearn: async () => {
    const { pendingPayload } = useLearnStore.getState();
    const effectivePayload = pendingSubmitPayload ?? pendingPayload ?? {};
    pendingSubmitPayload = null;
    useLearnStore.setState({ pendingPayload: null });
    await useLearnStore.getState().submitLearn(effectivePayload);
  },

  submitLearn: async (payload) => {
    const { phase } = useLearnStore.getState();
    if (phase === 'submitting' || phase === 'running' || phase === 'cancelling') return;
    const generation = ++submitGeneration;
    const effectivePayload = payload ?? {};
    const safePayload = stripSensitivePayload(effectivePayload);
    const retryable = effectivePayload.patch === undefined && effectivePayload.patch_url === undefined;
    pendingSubmitPayload = null;
    useLearnStore.setState({
      phase: 'submitting',
      error: null,
      errorCode: null,
      task: null,
      taskId: null,
      lastPayload: safePayload,
      pendingPayload: null,
      retryable,
    });
    try {
      const res = await startLearnTask(effectivePayload);
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      consecutiveErrors = 0;
      useLearnStore.setState({ phase: 'running', taskId: res.task_id });
      startProgressTracking(res.task_id);
    } catch (err: unknown) {
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      if (isAbortError(err)) {
        useLearnStore.setState({
          phase: 'failed',
          error: null,
          errorCode: 'submit_aborted',
        });
        return;
      }
      let msg = err instanceof Error ? err.message : 'Submit failed';
      let code = 'submit_failed';
      if (err instanceof ApiError && err.status === 429) {
        const body = err.body;
        const retryAfter = body && typeof body === 'object' && !Array.isArray(body)
          ? (body as Record<string, unknown>).retry_after
          : undefined;
        code = 'rate_limited';
        const seconds = typeof retryAfter === 'number' ? String(retryAfter) : '60';
        msg = `rate_limited:${seconds}`;
      } else if (err instanceof ApiError && err.status === 503) {
        const body = err.body;
        const errField = body && typeof body === 'object' && !Array.isArray(body)
          ? (body as Record<string, unknown>).error
          : undefined;
        if (typeof errField === 'string' && errField.includes('too_many_pending')) {
          code = 'too_many_tasks';
          msg = 'A learn task is already running';
        }
      } else if (err instanceof ApiError && err.errorCode) {
        code = err.errorCode;
        msg = err.message;
      }
      useLearnStore.setState({ phase: 'failed', error: msg, errorCode: code });
    }
  },

  retryLearn: async () => {
    const { lastPayload, retryable, errorCode, taskId } = useLearnStore.getState();
    if (!retryable) return;
    // When polling lost contact with the backend, the task may still be
    // running server-side. Reconnect by resuming polling on the existing
    // taskId rather than submitting a new one (which would hit the 10
    // req/min rate limit and create a duplicate task).
    if (taskId && (errorCode === 'poll_connection_lost' || errorCode === 'poll_server_error')) {
      useLearnStore.getState().reconnectPoll();
      return;
    }
    await useLearnStore.getState().submitLearn(lastPayload ?? {});
  },

  reconnectPoll: () => {
    const { taskId } = useLearnStore.getState();
    if (!taskId) return;
    consecutiveErrors = 0;
    useLearnStore.setState({
      phase: 'running',
      error: null,
      errorCode: null,
    });
    startProgressTracking(taskId);
  },

  cancelLearn: async () => {
    const { taskId, phase } = useLearnStore.getState();
    if (!taskId || phase !== 'running') return;
    useLearnStore.setState({ phase: 'cancelling' });
    try {
      await cancelTask(taskId);
    } catch {
      if (useLearnStore.getState().phase === 'cancelling') {
        useLearnStore.setState({ phase: 'running' });
      }
    }
  },

  dismiss: () => {
    submitGeneration += 1;
    pendingSubmitPayload = null;
    resetPollState();
    useLearnStore.setState({ phase: 'idle', taskId: null, task: null, estimate: null, error: null, errorCode: null, pendingPayload: null });
  },

  recoverExistingTask: async () => {
    const { phase } = useLearnStore.getState();
    if (phase !== 'idle') return;
    try {
      const { tasks } = await listTasks();
      const active = tasks.find(
        (t) => t.task_type === 'learn' && (t.status === 'running' || t.status === 'pending'),
      );
      if (!active) return;
      if (useLearnStore.getState().phase !== 'idle') return;
      consecutiveErrors = 0;
      useLearnStore.setState({
        phase: 'running',
        taskId: active.task_id,
        task: active,
        lastPayload: null,
        retryable: false,
      });
      startProgressTracking(active.task_id);
    } catch {
      // Recovery is best-effort
    }
  },
}));
