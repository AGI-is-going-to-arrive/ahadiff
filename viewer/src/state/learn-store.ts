import { create } from 'zustand';
import { startLearnTask, getTask, cancelTask, listTasks } from '../api/tasks';
import { ApiError } from '../api/client';
import { useRunsStore } from './runs-store';
import { useGraphStore } from './graph-store';
import type { TaskInfoResponse, LearnSubmitPayload } from '../api/types';

type LearnPhase =
  | 'idle'
  | 'submitting'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'cancelling';

const POLL_INTERVAL_MS = 1500;
const MAX_POLL_INTERVAL_MS = 30_000;
const MAX_POLL_DURATION_MS = 660_000;

let pollTimer: ReturnType<typeof setTimeout> | null = null;
let submitGeneration = 0;
let consecutiveErrors = 0;
let pollStartedAt = 0;

interface LearnState {
  phase: LearnPhase;
  taskId: string | null;
  task: TaskInfoResponse | null;
  error: string | null;
  errorCode: string | null;
  lastPayload: LearnSubmitPayload | null;
  retryable: boolean;

  submitLearn: (payload?: LearnSubmitPayload) => Promise<void>;
  retryLearn: () => Promise<void>;
  cancelLearn: () => Promise<void>;
  dismiss: () => void;
  recoverExistingTask: () => Promise<void>;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function resetPollState(): void {
  stopPolling();
  consecutiveErrors = 0;
  pollStartedAt = 0;
}

function schedulePoll(): void {
  stopPolling();
  const interval = consecutiveErrors === 0
    ? POLL_INTERVAL_MS
    : Math.min(POLL_INTERVAL_MS * 2 ** consecutiveErrors, MAX_POLL_INTERVAL_MS);
  pollTimer = setTimeout(() => void doPoll(), interval);
}

async function doPoll(): Promise<void> {
  const state = useLearnStore.getState();
  const { taskId, phase } = state;
  if (!taskId || (phase !== 'running' && phase !== 'cancelling')) {
    resetPollState();
    return;
  }
  if (pollStartedAt > 0 && Date.now() - pollStartedAt > MAX_POLL_DURATION_MS) {
    useLearnStore.setState({
      phase: 'failed',
      error: 'Learn run timed out',
      errorCode: 'timeout',
    });
    resetPollState();
    return;
  }
  const capturedTaskId = taskId;
  try {
    const info = await getTask(capturedTaskId);
    if (useLearnStore.getState().taskId !== capturedTaskId) return;
    consecutiveErrors = 0;
    const s = info.status;
    if (s === 'completed') {
      useLearnStore.setState({ phase: 'completed', task: info });
      useRunsStore.setState({ lastLoadedAt: null });
      useGraphStore.getState().invalidate();
      resetPollState();
    } else if (s === 'cancelled') {
      useLearnStore.setState({ phase: 'cancelled', task: info });
      resetPollState();
    } else if (s === 'failed') {
      useLearnStore.setState({
        phase: 'failed',
        task: info,
        error: info.error ?? 'Task failed',
        errorCode: info.error_code ?? 'internal_error',
      });
      resetPollState();
    } else {
      useLearnStore.setState({ task: info });
      schedulePoll();
    }
  } catch {
    const current = useLearnStore.getState();
    if (current.taskId !== capturedTaskId || (current.phase !== 'running' && current.phase !== 'cancelling')) return;
    consecutiveErrors += 1;
    schedulePoll();
  }
}

export const useLearnStore = create<LearnState>(() => ({
  phase: 'idle',
  taskId: null,
  task: null,
  error: null,
  errorCode: null,
  lastPayload: null,
  retryable: true,

  submitLearn: async (payload) => {
    const { phase } = useLearnStore.getState();
    if (phase === 'submitting' || phase === 'running' || phase === 'cancelling') return;
    const generation = ++submitGeneration;
    const effectivePayload = payload ?? {};
    const { patch: _p, patch_url: _u, ...safePayload } = effectivePayload;
    const retryable = _p === undefined && _u === undefined;
    useLearnStore.setState({
      phase: 'submitting',
      error: null,
      errorCode: null,
      task: null,
      taskId: null,
      lastPayload: safePayload,
      retryable,
    });
    try {
      const res = await startLearnTask(effectivePayload);
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      pollStartedAt = Date.now();
      consecutiveErrors = 0;
      useLearnStore.setState({ phase: 'running', taskId: res.task_id });
      schedulePoll();
    } catch (err: unknown) {
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      if (err instanceof DOMException && err.name === 'AbortError') {
        useLearnStore.setState({
          phase: 'failed',
          error: 'Learn request was aborted. Please retry.',
          errorCode: 'submit_aborted',
        });
        return;
      }
      let msg = err instanceof Error ? err.message : 'Submit failed';
      let code = 'submit_failed';
      if (err instanceof ApiError && err.status === 503) {
        const body = err.body;
        const errField = body && typeof body === 'object' && !Array.isArray(body)
          ? (body as Record<string, unknown>).error
          : undefined;
        if (typeof errField === 'string' && errField.includes('too_many_pending')) {
          code = 'too_many_tasks';
          msg = 'A learn task is already running';
        }
      }
      useLearnStore.setState({ phase: 'failed', error: msg, errorCode: code });
    }
  },

  retryLearn: async () => {
    const { lastPayload, retryable } = useLearnStore.getState();
    if (!retryable) return;
    await useLearnStore.getState().submitLearn(lastPayload ?? {});
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
    resetPollState();
    useLearnStore.setState({ phase: 'idle', taskId: null, task: null, error: null, errorCode: null });
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
      pollStartedAt = Date.now();
      consecutiveErrors = 0;
      useLearnStore.setState({
        phase: 'running',
        taskId: active.task_id,
        task: active,
        lastPayload: null,
        retryable: false,
      });
      schedulePoll();
    } catch {
      // Recovery is best-effort
    }
  },
}));
