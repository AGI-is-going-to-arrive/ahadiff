import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startLearnTask, getTask, cancelTask, listTasks } from '../api/tasks';
import { ApiError } from '../api/client';
import { useRunsStore } from './runs-store';
import { useLearnStore } from './learn-store';
import type { TaskInfoResponse, TaskSubmitResponse } from '../api/types';

const graphInvalidateMock = vi.hoisted(() => vi.fn());

vi.mock('../api/tasks', () => ({
  startLearnTask: vi.fn(),
  getTask: vi.fn(),
  cancelTask: vi.fn(),
  listTasks: vi.fn(),
}));

vi.mock('./graph-store', () => ({
  useGraphStore: {
    getState: () => ({ invalidate: graphInvalidateMock }),
  },
}));

const mockedStartLearnTask = vi.mocked(startLearnTask);
const mockedGetTask = vi.mocked(getTask);
const mockedCancelTask = vi.mocked(cancelTask);
const mockedListTasks = vi.mocked(listTasks);

function makeTaskInfo(overrides: Partial<TaskInfoResponse> = {}): TaskInfoResponse {
  return {
    task_id: 'task-1',
    task_type: 'learn',
    status: 'running',
    progress: { current: 0, total: 10, message: '' },
    created_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

describe('learn store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useLearnStore.setState({
      phase: 'idle',
      taskId: null,
      task: null,
      error: null,
      errorCode: null,
      lastPayload: null,
      retryable: true,
    });
    useRunsStore.setState({ lastLoadedAt: Date.now() });
    graphInvalidateMock.mockClear();
  });

  afterEach(() => {
    useLearnStore.getState().dismiss();
    vi.useRealTimers();
  });

  // ---------- submitLearn ----------

  it('submitLearn transitions from idle to submitting then running', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' } satisfies TaskSubmitResponse);

    const promise = useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('submitting');

    await promise;
    expect(useLearnStore.getState().phase).toBe('running');
    expect(useLearnStore.getState().taskId).toBe('task-1');
    expect(mockedStartLearnTask).toHaveBeenCalledWith({});
  });

  it('submitLearn sets phase to failed on rejection', async () => {
    mockedStartLearnTask.mockRejectedValue(new Error('network down'));

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().error).toBe('network down');
    expect(useLearnStore.getState().errorCode).toBe('submit_failed');
  });

  it('submitLearn turns AbortError into a retryable failed state', async () => {
    mockedStartLearnTask.mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError'),
    );

    const promise = useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('submitting');

    await promise;
    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().errorCode).toBe('submit_aborted');
    expect(useLearnStore.getState().error).toBe('Learn request was aborted. Please retry.');
    expect(useLearnStore.getState().retryable).toBe(true);
  });

  it('dismiss during submit prevents a stale submit response from reviving the task', async () => {
    let resolveStart: ((v: TaskSubmitResponse) => void) | null = null;
    mockedStartLearnTask.mockImplementation(
      () =>
        new Promise<TaskSubmitResponse>((resolve) => {
          resolveStart = resolve;
        }),
    );

    const promise = useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('submitting');

    useLearnStore.getState().dismiss();
    expect(useLearnStore.getState().phase).toBe('idle');

    resolveStart!({ task_id: 'task-stale' });
    await promise;

    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().taskId).toBeNull();
    await vi.advanceTimersByTimeAsync(3000);
    expect(mockedGetTask).not.toHaveBeenCalled();
  });

  it('submitLearn is a no-op while already running', async () => {
    useLearnStore.setState({ phase: 'running', taskId: 'task-existing' });

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().phase).toBe('running');
    expect(useLearnStore.getState().taskId).toBe('task-existing');
    expect(mockedStartLearnTask).not.toHaveBeenCalled();
  });

  it('submitLearn is a no-op while submitting', async () => {
    useLearnStore.setState({ phase: 'submitting' });

    await useLearnStore.getState().submitLearn();

    expect(mockedStartLearnTask).not.toHaveBeenCalled();
  });

  it('submitLearn is a no-op while cancelling', async () => {
    useLearnStore.setState({ phase: 'cancelling', taskId: 'task-cancel' });

    await useLearnStore.getState().submitLearn();

    expect(mockedStartLearnTask).not.toHaveBeenCalled();
  });

  it('submitLearn stores lastPayload', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const payload = { last: true, lang: 'en' as const };

    await useLearnStore.getState().submitLearn(payload);

    expect(useLearnStore.getState().lastPayload).toEqual(payload);
    expect(useLearnStore.getState().retryable).toBe(true);
    expect(mockedStartLearnTask).toHaveBeenCalledWith(payload);
  });

  it('submitLearn defaults to empty payload when called with no args', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().lastPayload).toEqual({});
    expect(useLearnStore.getState().retryable).toBe(true);
    expect(mockedStartLearnTask).toHaveBeenCalledWith({});
  });

  // ---------- 503 too_many_tasks ----------

  it('submitLearn detects 503 too_many_pending as too_many_tasks', async () => {
    mockedStartLearnTask.mockRejectedValue(
      new ApiError(503, { error: 'too_many_pending_learn_tasks', status: 503 }),
    );

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().errorCode).toBe('too_many_tasks');
    expect(useLearnStore.getState().error).toBe('A learn task is already running');
  });

  it('submitLearn treats non-matching 503 as regular submit_failed', async () => {
    mockedStartLearnTask.mockRejectedValue(
      new ApiError(503, { error: 'service_unavailable', status: 503 }),
    );

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().errorCode).toBe('submit_failed');
  });

  // ---------- retryLearn ----------

  it('retryLearn reuses lastPayload', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const payload = { revision: 'abc123' };

    await useLearnStore.getState().submitLearn(payload);
    useLearnStore.getState().dismiss();
    expect(useLearnStore.getState().lastPayload).toEqual(payload);

    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-2' });
    await useLearnStore.getState().retryLearn();

    expect(mockedStartLearnTask).toHaveBeenLastCalledWith(payload);
    expect(useLearnStore.getState().taskId).toBe('task-2');
  });

  it('retryLearn defaults to empty payload when no prior submit', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });

    await useLearnStore.getState().retryLearn();

    expect(mockedStartLearnTask).toHaveBeenCalledWith({});
  });

  it('retryLearn works directly from failed state without dismiss', async () => {
    const payload = { last: true };
    mockedStartLearnTask.mockRejectedValueOnce(new Error('fail'));
    await useLearnStore.getState().submitLearn(payload);
    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().lastPayload).toEqual({ last: true });

    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-retry' });
    await useLearnStore.getState().retryLearn();
    expect(useLearnStore.getState().taskId).toBe('task-retry');
    expect(mockedStartLearnTask).toHaveBeenLastCalledWith({ last: true });
  });

  it('lastPayload strips sensitive fields (patch, patch_url)', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    await useLearnStore.getState().submitLearn({ last: true, patch: 'secret-diff', patch_url: 'https://secret' });
    expect(useLearnStore.getState().lastPayload).toEqual({ last: true });
    expect(useLearnStore.getState().retryable).toBe(false);
    expect(useLearnStore.getState().lastPayload).not.toHaveProperty('patch');
    expect(useLearnStore.getState().lastPayload).not.toHaveProperty('patch_url');
  });

  it('retryLearn is a no-op for patch-backed submits', async () => {
    mockedStartLearnTask.mockRejectedValueOnce(new Error('fail'));
    await useLearnStore.getState().submitLearn({ patch: 'secret-diff' });
    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().retryable).toBe(false);

    mockedStartLearnTask.mockClear();
    await useLearnStore.getState().retryLearn();

    expect(mockedStartLearnTask).not.toHaveBeenCalled();
    expect(useLearnStore.getState().phase).toBe('failed');
  });

  // ---------- cancelLearn ----------

  it('cancelLearn transitions from running to cancelling', async () => {
    mockedCancelTask.mockResolvedValue({ cancelled: true });
    useLearnStore.setState({ phase: 'running', taskId: 'task-1' });

    const promise = useLearnStore.getState().cancelLearn();
    expect(useLearnStore.getState().phase).toBe('cancelling');

    await promise;
    expect(useLearnStore.getState().phase).toBe('cancelling');
    expect(mockedCancelTask).toHaveBeenCalledWith('task-1');
  });

  it('cancelLearn reverts to running on rejection', async () => {
    mockedCancelTask.mockRejectedValue(new Error('cancel failed'));
    useLearnStore.setState({ phase: 'running', taskId: 'task-1' });

    await useLearnStore.getState().cancelLearn();

    expect(useLearnStore.getState().phase).toBe('running');
  });

  it('cancelLearn rejection does not revert terminal state', async () => {
    mockedCancelTask.mockRejectedValue(new Error('cancel failed'));
    useLearnStore.setState({ phase: 'running', taskId: 'task-1' });

    const promise = useLearnStore.getState().cancelLearn();
    expect(useLearnStore.getState().phase).toBe('cancelling');

    // Simulate poll completing before cancel rejects
    useLearnStore.setState({ phase: 'completed' });
    await promise;

    // Phase should stay completed, not revert to running
    expect(useLearnStore.getState().phase).toBe('completed');
  });

  it('cancelLearn is a no-op when not running', async () => {
    useLearnStore.setState({ phase: 'idle', taskId: null });

    await useLearnStore.getState().cancelLearn();

    expect(mockedCancelTask).not.toHaveBeenCalled();
  });

  // ---------- dismiss ----------

  it('dismiss resets all state to idle and stops polling', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockResolvedValue(makeTaskInfo({ status: 'running' }));

    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    useLearnStore.getState().dismiss();

    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().taskId).toBeNull();
    expect(useLearnStore.getState().task).toBeNull();
    expect(useLearnStore.getState().error).toBeNull();
    expect(useLearnStore.getState().errorCode).toBeNull();

    await vi.advanceTimersByTimeAsync(3000);
    expect(mockedGetTask).not.toHaveBeenCalled();
  });

  // ---------- poll lifecycle ----------

  it('stale poll response does not update state after dismiss', async () => {
    let resolveGetTask: ((v: TaskInfoResponse) => void) | null = null;
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockImplementation(
      () =>
        new Promise<TaskInfoResponse>((resolve) => {
          resolveGetTask = resolve;
        }),
    );

    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);

    useLearnStore.getState().dismiss();
    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().taskId).toBeNull();

    resolveGetTask!(makeTaskInfo({ status: 'completed' }));
    await vi.advanceTimersByTimeAsync(0);

    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().task).toBeNull();
  });

  it('poll transitions to completed and invalidates runs store', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });

    const completedTask = makeTaskInfo({ task_id: 'task-1', status: 'completed' });
    mockedGetTask
      .mockResolvedValueOnce(makeTaskInfo({ task_id: 'task-1', status: 'running' }))
      .mockResolvedValueOnce(completedTask);

    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);
    expect(useLearnStore.getState().phase).toBe('running');

    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    expect(useLearnStore.getState().phase).toBe('completed');
    expect(useLearnStore.getState().task).toEqual(completedTask);

    expect(useRunsStore.getState().lastLoadedAt).toBeNull();
    expect(graphInvalidateMock).toHaveBeenCalledTimes(1);
  });

  it('poll transitions to failed when task status is failed', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const failedTask = makeTaskInfo({
      task_id: 'task-1',
      status: 'failed',
      error: 'Out of memory',
      error_code: 'internal_error',
    });
    mockedGetTask.mockResolvedValue(failedTask);

    await useLearnStore.getState().submitLearn();
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().error).toBe('Out of memory');
    expect(useLearnStore.getState().errorCode).toBe('internal_error');
    expect(useLearnStore.getState().task).toEqual(failedTask);
  });

  it('poll disables retry when recovery_hint is not retry', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockResolvedValue(
      makeTaskInfo({
        task_id: 'task-1',
        status: 'failed',
        error: 'Configuration error. Check your provider settings.',
        error_code: 'config_error',
        recovery_hint: 'check_config',
      }),
    );

    await useLearnStore.getState().submitLearn({ last: true });
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().retryable).toBe(false);

    mockedStartLearnTask.mockClear();
    await useLearnStore.getState().retryLearn();
    expect(mockedStartLearnTask).not.toHaveBeenCalled();
  });

  it('poll keeps retry enabled when recovery_hint is retry', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockResolvedValue(
      makeTaskInfo({
        task_id: 'task-1',
        status: 'failed',
        error: 'Task timed out. Try again or increase the timeout.',
        error_code: 'timeout',
        recovery_hint: 'retry',
      }),
    );

    await useLearnStore.getState().submitLearn({ last: true });
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().retryable).toBe(true);
  });

  it('poll transitions to cancelled without invalidating run or graph state', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const cancelledTask = makeTaskInfo({ task_id: 'task-1', status: 'cancelled' });
    mockedGetTask.mockResolvedValue(cancelledTask);
    const previousLastLoadedAt = useRunsStore.getState().lastLoadedAt;

    await useLearnStore.getState().submitLearn();
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('cancelled');
    expect(useRunsStore.getState().lastLoadedAt).toBe(previousLastLoadedAt);
    expect(graphInvalidateMock).not.toHaveBeenCalled();
  });

  // ---------- poll stale rejection guard ----------

  it('stale poll rejection after dismiss does not corrupt next task backoff', async () => {
    let rejectGetTask: ((err: Error) => void) | null = null;
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockImplementation(
      () =>
        new Promise<TaskInfoResponse>((_resolve, reject) => {
          rejectGetTask = reject;
        }),
    );

    // Start task-1, trigger poll
    await useLearnStore.getState().submitLearn();
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);

    // Dismiss while poll is in-flight
    useLearnStore.getState().dismiss();
    expect(useLearnStore.getState().phase).toBe('idle');

    // Start task-2
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-2' });
    mockedGetTask.mockResolvedValue(makeTaskInfo({ task_id: 'task-2', status: 'running' }));
    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().taskId).toBe('task-2');

    // Now the stale task-1 poll rejects
    rejectGetTask!(new Error('stale network error'));
    await vi.advanceTimersByTimeAsync(0);

    // task-2's poll should fire at normal 1500ms (not backoff-delayed)
    await vi.advanceTimersByTimeAsync(1500);
    // 2 calls: 1 stale (from task-1) + 1 fresh poll (for task-2)
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    expect(useLearnStore.getState().taskId).toBe('task-2');
    expect(useLearnStore.getState().phase).toBe('running');
  });

  // ---------- poll exponential backoff ----------

  it('poll uses exponential backoff on consecutive network errors', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockRejectedValue(new Error('network error'));

    await useLearnStore.getState().submitLearn();

    // First poll at 1500ms - fails
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);
    expect(useLearnStore.getState().phase).toBe('running');

    // Second poll should be at 3000ms (1500 * 2^1)
    await vi.advanceTimersByTimeAsync(2999);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);

    // Third poll should be at 6000ms (1500 * 2^2)
    await vi.advanceTimersByTimeAsync(5999);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(mockedGetTask).toHaveBeenCalledTimes(3);
  });

  it('poll backoff resets on successful response', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask
      .mockRejectedValueOnce(new Error('network error'))
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce(makeTaskInfo({ task_id: 'task-1', status: 'running' }))
      .mockResolvedValueOnce(makeTaskInfo({ task_id: 'task-1', status: 'completed' }));

    await useLearnStore.getState().submitLearn();

    // 1st poll at 1500ms - error
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);

    // 2nd poll at 1500+3000=4500ms - error
    await vi.advanceTimersByTimeAsync(3000);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);

    // 3rd poll at 4500+6000=10500ms - success
    await vi.advanceTimersByTimeAsync(6000);
    expect(mockedGetTask).toHaveBeenCalledTimes(3);
    expect(useLearnStore.getState().phase).toBe('running');

    // 4th poll should be back at 1500ms (backoff reset)
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(4);
    expect(useLearnStore.getState().phase).toBe('completed');
  });

  it('poll backoff caps at 30 seconds', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockRejectedValue(new Error('network error'));

    await useLearnStore.getState().submitLearn();

    // Run through several error cycles to reach cap
    // 1500, 3000, 6000, 12000, 24000, 30000 (capped)
    let totalTime = 0;
    for (let i = 0; i < 6; i++) {
      const expected = Math.min(1500 * 2 ** i, 30_000);
      totalTime += expected;
      await vi.advanceTimersByTimeAsync(expected);
    }
    const callsBefore = mockedGetTask.mock.calls.length;

    // Next interval should still be 30000 (capped)
    await vi.advanceTimersByTimeAsync(29_999);
    expect(mockedGetTask).toHaveBeenCalledTimes(callsBefore);
    await vi.advanceTimersByTimeAsync(1);
    expect(mockedGetTask).toHaveBeenCalledTimes(callsBefore + 1);
  });

  // ---------- poll timeout ----------

  it('poll times out after MAX_POLL_DURATION_MS', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockResolvedValue(makeTaskInfo({ task_id: 'task-1', status: 'running' }));

    await useLearnStore.getState().submitLearn();

    // Advance past the 660s timeout
    // Each poll takes 1500ms, so we need 660000/1500 = 440 polls
    // But let's just jump to 661s
    const pollCount = Math.ceil(660_000 / 1500);
    for (let i = 0; i < pollCount + 1; i++) {
      await vi.advanceTimersByTimeAsync(1500);
    }

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().errorCode).toBe('timeout');
    expect(useLearnStore.getState().error).toBe('Learn run timed out');
  });

  // ---------- recoverExistingTask ----------

  it('recoverExistingTask picks up a running task', async () => {
    const runningTask = makeTaskInfo({ task_id: 'task-recovered', status: 'running' });
    mockedListTasks.mockResolvedValue({ tasks: [runningTask] });
    mockedGetTask.mockResolvedValue(makeTaskInfo({ task_id: 'task-recovered', status: 'completed' }));

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().phase).toBe('running');
    expect(useLearnStore.getState().taskId).toBe('task-recovered');
    expect(useLearnStore.getState().task).toEqual(runningTask);
    expect(useLearnStore.getState().lastPayload).toBeNull();
    expect(useLearnStore.getState().retryable).toBe(false);

    // Verify polling starts
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledWith('task-recovered');
    expect(useLearnStore.getState().phase).toBe('completed');
  });

  it('recovered task failure cannot retry with an unknown payload', async () => {
    const runningTask = makeTaskInfo({ task_id: 'task-recovered', status: 'running' });
    mockedListTasks.mockResolvedValue({ tasks: [runningTask] });
    mockedGetTask.mockResolvedValue(
      makeTaskInfo({
        task_id: 'task-recovered',
        status: 'failed',
        error: 'Recovered task failed',
      }),
    );

    await useLearnStore.getState().recoverExistingTask();
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().retryable).toBe(false);

    mockedStartLearnTask.mockClear();
    await useLearnStore.getState().retryLearn();
    expect(mockedStartLearnTask).not.toHaveBeenCalled();
  });

  it('recoverExistingTask picks up a pending task', async () => {
    const pendingTask = makeTaskInfo({ task_id: 'task-pending', status: 'pending' });
    mockedListTasks.mockResolvedValue({ tasks: [pendingTask] });

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().phase).toBe('running');
    expect(useLearnStore.getState().taskId).toBe('task-pending');
  });

  it('recoverExistingTask is a no-op when no active tasks', async () => {
    mockedListTasks.mockResolvedValue({ tasks: [] });

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().phase).toBe('idle');
  });

  it('recoverExistingTask is a no-op when not idle', async () => {
    useLearnStore.setState({ phase: 'running', taskId: 'task-existing' });
    mockedListTasks.mockResolvedValue({
      tasks: [makeTaskInfo({ task_id: 'task-other', status: 'running' })],
    });

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().taskId).toBe('task-existing');
    expect(mockedListTasks).not.toHaveBeenCalled();
  });

  it('recoverExistingTask ignores completed tasks', async () => {
    mockedListTasks.mockResolvedValue({
      tasks: [makeTaskInfo({ task_id: 'task-done', status: 'completed' })],
    });

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().phase).toBe('idle');
  });

  it('recoverExistingTask silently ignores network errors', async () => {
    mockedListTasks.mockRejectedValue(new Error('network error'));

    await useLearnStore.getState().recoverExistingTask();

    expect(useLearnStore.getState().phase).toBe('idle');
  });
});
