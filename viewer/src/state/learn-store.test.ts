import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startLearnTask, getTask, cancelTask } from '../api/tasks';
import { useRunsStore } from './runs-store';
import { useLearnStore } from './learn-store';
import type { TaskInfoResponse, TaskSubmitResponse } from '../api/types';

vi.mock('../api/tasks', () => ({
  startLearnTask: vi.fn(),
  getTask: vi.fn(),
  cancelTask: vi.fn(),
  listTasks: vi.fn(),
}));

const mockedStartLearnTask = vi.mocked(startLearnTask);
const mockedGetTask = vi.mocked(getTask);
const mockedCancelTask = vi.mocked(cancelTask);

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
    // Reset store to idle
    useLearnStore.setState({
      phase: 'idle',
      taskId: null,
      task: null,
      error: null,
      errorCode: null,
    });
    // Reset runs store lastLoadedAt so we can detect invalidation
    useRunsStore.setState({ lastLoadedAt: Date.now() });
  });

  afterEach(() => {
    // Dismiss to clear any lingering poll timers
    useLearnStore.getState().dismiss();
    vi.useRealTimers();
  });

  // 1. submitLearn happy path
  it('submitLearn transitions from idle to submitting then running', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' } satisfies TaskSubmitResponse);

    const promise = useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('submitting');

    await promise;
    expect(useLearnStore.getState().phase).toBe('running');
    expect(useLearnStore.getState().taskId).toBe('task-1');
    expect(mockedStartLearnTask).toHaveBeenCalledWith({});
  });

  // 2. submitLearn error
  it('submitLearn sets phase to failed on rejection', async () => {
    mockedStartLearnTask.mockRejectedValue(new Error('network down'));

    await useLearnStore.getState().submitLearn();

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().error).toBe('network down');
    expect(useLearnStore.getState().errorCode).toBe('submit_failed');
  });

  // 3. submitLearn AbortError
  it('submitLearn ignores AbortError and stays in submitting', async () => {
    mockedStartLearnTask.mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError'),
    );

    const promise = useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('submitting');

    await promise;

    // Phase should NOT become failed -- the AbortError is silently swallowed.
    // It stays at submitting since no further setState is called after AbortError return.
    expect(useLearnStore.getState().phase).toBe('submitting');
    expect(useLearnStore.getState().error).toBeNull();
  });

  // 4. submitLearn while busy
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

  // 5. cancelLearn happy path
  it('cancelLearn transitions from running to cancelling', async () => {
    mockedCancelTask.mockResolvedValue({ cancelled: true });
    useLearnStore.setState({ phase: 'running', taskId: 'task-1' });

    const promise = useLearnStore.getState().cancelLearn();
    expect(useLearnStore.getState().phase).toBe('cancelling');

    await promise;
    expect(useLearnStore.getState().phase).toBe('cancelling');
    expect(mockedCancelTask).toHaveBeenCalledWith('task-1');
  });

  // 6. cancelLearn error
  it('cancelLearn reverts to running on rejection', async () => {
    mockedCancelTask.mockRejectedValue(new Error('cancel failed'));
    useLearnStore.setState({ phase: 'running', taskId: 'task-1' });

    await useLearnStore.getState().cancelLearn();

    expect(useLearnStore.getState().phase).toBe('running');
  });

  it('cancelLearn is a no-op when not running', async () => {
    useLearnStore.setState({ phase: 'idle', taskId: null });

    await useLearnStore.getState().cancelLearn();

    expect(mockedCancelTask).not.toHaveBeenCalled();
  });

  // 7. dismiss
  it('dismiss resets all state to idle and stops polling', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockResolvedValue(makeTaskInfo({ status: 'running' }));

    // Start a learn task so polling is active
    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    useLearnStore.getState().dismiss();

    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().taskId).toBeNull();
    expect(useLearnStore.getState().task).toBeNull();
    expect(useLearnStore.getState().error).toBeNull();
    expect(useLearnStore.getState().errorCode).toBeNull();

    // Advance timers past poll interval -- getTask should NOT be called
    // because polling was stopped
    await vi.advanceTimersByTimeAsync(3000);
    expect(mockedGetTask).not.toHaveBeenCalled();
  });

  // 8. poll stale taskId guard
  it('stale poll response does not update state after dismiss', async () => {
    let resolveGetTask: ((v: TaskInfoResponse) => void) | null = null;
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask.mockImplementation(
      () =>
        new Promise<TaskInfoResponse>((resolve) => {
          resolveGetTask = resolve;
        }),
    );

    // Start learn, enter running phase
    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    // Trigger the poll by advancing to poll interval
    await vi.advanceTimersByTimeAsync(1500);
    // getTask should have been called
    expect(mockedGetTask).toHaveBeenCalledTimes(1);

    // Dismiss while poll is in-flight
    useLearnStore.getState().dismiss();
    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().taskId).toBeNull();

    // Now resolve the stale getTask -- it should be a no-op due to taskId guard
    resolveGetTask!(makeTaskInfo({ status: 'completed' }));
    await vi.advanceTimersByTimeAsync(0);

    // State should remain idle, not completed
    expect(useLearnStore.getState().phase).toBe('idle');
    expect(useLearnStore.getState().task).toBeNull();
  });

  // 9. poll completion
  it('poll transitions to completed and invalidates runs store', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });

    // First poll returns running, second returns completed
    const completedTask = makeTaskInfo({ task_id: 'task-1', status: 'completed' });
    mockedGetTask
      .mockResolvedValueOnce(makeTaskInfo({ task_id: 'task-1', status: 'running' }))
      .mockResolvedValueOnce(completedTask);

    // Start learn
    await useLearnStore.getState().submitLearn();
    expect(useLearnStore.getState().phase).toBe('running');

    // First poll -- still running, reschedules
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);
    expect(useLearnStore.getState().phase).toBe('running');

    // Second poll -- completed
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    expect(useLearnStore.getState().phase).toBe('completed');
    expect(useLearnStore.getState().task).toEqual(completedTask);

    // Runs store lastLoadedAt should be invalidated (set to null)
    expect(useRunsStore.getState().lastLoadedAt).toBeNull();
  });

  // Extra: poll failure transitions to failed phase
  it('poll transitions to failed when task status is failed', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const failedTask = makeTaskInfo({
      task_id: 'task-1',
      status: 'failed',
      error: 'Out of memory',
      error_code: 'oom',
    });
    mockedGetTask.mockResolvedValue(failedTask);

    await useLearnStore.getState().submitLearn();
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('failed');
    expect(useLearnStore.getState().error).toBe('Out of memory');
    expect(useLearnStore.getState().errorCode).toBe('oom');
    expect(useLearnStore.getState().task).toEqual(failedTask);
  });

  // Extra: poll network error reschedules instead of crashing
  it('poll reschedules on network error without crashing', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    mockedGetTask
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce(makeTaskInfo({ task_id: 'task-1', status: 'completed' }));

    await useLearnStore.getState().submitLearn();

    // First poll -- network error, should reschedule
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(1);
    expect(useLearnStore.getState().phase).toBe('running');

    // Second poll -- completed
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    expect(useLearnStore.getState().phase).toBe('completed');
  });

  // Extra: cancelled task status transitions to completed
  it('poll transitions to completed when task status is cancelled', async () => {
    mockedStartLearnTask.mockResolvedValue({ task_id: 'task-1' });
    const cancelledTask = makeTaskInfo({ task_id: 'task-1', status: 'cancelled' });
    mockedGetTask.mockResolvedValue(cancelledTask);

    await useLearnStore.getState().submitLearn();
    await vi.advanceTimersByTimeAsync(1500);

    expect(useLearnStore.getState().phase).toBe('completed');
    expect(useRunsStore.getState().lastLoadedAt).toBeNull();
  });
});
