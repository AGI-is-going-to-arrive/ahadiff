import { create } from 'zustand';
import { startLearnTask, getTask, cancelTask } from '../api/tasks';
import { useRunsStore } from './runs-store';
import type { TaskInfoResponse, LearnSubmitPayload } from '../api/types';

type LearnPhase = 'idle' | 'submitting' | 'running' | 'completed' | 'failed' | 'cancelling';

const POLL_INTERVAL_MS = 1500;

let pollTimer: ReturnType<typeof setTimeout> | null = null;
let submitGeneration = 0;

interface LearnState {
  phase: LearnPhase;
  taskId: string | null;
  task: TaskInfoResponse | null;
  error: string | null;
  errorCode: string | null;

  submitLearn: (payload?: LearnSubmitPayload) => Promise<void>;
  cancelLearn: () => Promise<void>;
  dismiss: () => void;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll(): void {
  stopPolling();
  pollTimer = setTimeout(() => void doPoll(), POLL_INTERVAL_MS);
}

async function doPoll(): Promise<void> {
  const state = useLearnStore.getState();
  const { taskId, phase } = state;
  if (!taskId || (phase !== 'running' && phase !== 'cancelling')) {
    stopPolling();
    return;
  }
  const capturedTaskId = taskId;
  try {
    const info = await getTask(capturedTaskId);
    // Guard against stale response after dismiss/new submit
    if (useLearnStore.getState().taskId !== capturedTaskId) return;
    const s = info.status;
    if (s === 'completed' || s === 'cancelled') {
      useLearnStore.setState({ phase: 'completed', task: info });
      useRunsStore.setState({ lastLoadedAt: null });
      stopPolling();
    } else if (s === 'failed') {
      useLearnStore.setState({
        phase: 'failed',
        task: info,
        error: info.error ?? 'Task failed',
        errorCode: info.error_code ?? 'internal_error',
      });
      stopPolling();
    } else {
      useLearnStore.setState({ task: info });
      schedulePoll();
    }
  } catch {
    schedulePoll();
  }
}

export const useLearnStore = create<LearnState>(() => ({
  phase: 'idle',
  taskId: null,
  task: null,
  error: null,
  errorCode: null,

  submitLearn: async (payload) => {
    const { phase } = useLearnStore.getState();
    if (phase === 'submitting' || phase === 'running' || phase === 'cancelling') return;
    const generation = ++submitGeneration;
    useLearnStore.setState({ phase: 'submitting', error: null, errorCode: null, task: null, taskId: null });
    try {
      const res = await startLearnTask(payload ?? {});
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      useLearnStore.setState({ phase: 'running', taskId: res.task_id });
      schedulePoll();
    } catch (err: unknown) {
      if (submitGeneration !== generation || useLearnStore.getState().phase !== 'submitting') return;
      if (err instanceof DOMException && err.name === 'AbortError') return;
      const msg = err instanceof Error ? err.message : 'Submit failed';
      useLearnStore.setState({ phase: 'failed', error: msg, errorCode: 'submit_failed' });
    }
  },

  cancelLearn: async () => {
    const { taskId, phase } = useLearnStore.getState();
    if (!taskId || phase !== 'running') return;
    useLearnStore.setState({ phase: 'cancelling' });
    try {
      await cancelTask(taskId);
    } catch {
      useLearnStore.setState({ phase: 'running' });
    }
  },

  dismiss: () => {
    submitGeneration += 1;
    stopPolling();
    useLearnStore.setState({ phase: 'idle', taskId: null, task: null, error: null, errorCode: null });
  },
}));
