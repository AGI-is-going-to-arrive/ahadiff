import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LearnTaskBanner from './LearnTaskBanner';
import type { TaskInfoResponse } from '../api/types';

interface MockLearnState {
  phase: 'idle' | 'submitting' | 'running' | 'completed' | 'cancelled' | 'failed' | 'cancelling' | 'estimating' | 'confirming';
  task: TaskInfoResponse | null;
  estimate: unknown;
  error: string | null;
  errorCode: string | null;
  retryable: boolean;
  cancelLearn: () => void;
  confirmLearn: () => void;
  dismiss: () => void;
  retryLearn: () => void;
  recoverExistingTask: () => Promise<void>;
}

const cancelLearn = vi.fn();
const confirmLearn = vi.fn();
const dismiss = vi.fn();
const retryLearn = vi.fn();
const recoverExistingTask = vi.fn(async () => undefined);

let learnState: MockLearnState;

vi.mock('../state/learn-store', () => ({
  useLearnStore: (selector: (state: MockLearnState) => unknown) => selector(learnState),
}));

function makeTask(overrides: Partial<TaskInfoResponse> = {}): TaskInfoResponse {
  return {
    task_id: 'task-1',
    task_type: 'learn',
    status: 'failed',
    progress: { current: 0, total: 0, message: '', step_started_at: '' },
    result_summary: null,
    error: null,
    error_code: null,
    created_at: '2026-05-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    elapsed_seconds: null,
    recovery_hint: null,
    ...overrides,
  };
}

describe('LearnTaskBanner', () => {
  beforeEach(() => {
    learnState = {
      phase: 'failed',
      task: null,
      estimate: null,
      error: null,
      errorCode: null,
      retryable: true,
      cancelLearn,
      confirmLearn,
      dismiss,
      retryLearn,
      recoverExistingTask,
    };
    vi.clearAllMocks();
  });

  it('does not show Retry when task recovery_hint is not retry', () => {
    learnState.task = makeTask({
      error: 'Configuration error. Check your provider settings.',
      error_code: 'config_error',
      recovery_hint: 'check_config',
    });
    learnState.error = 'Configuration error. Check your provider settings.';
    learnState.errorCode = 'config_error';

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    expect(html).not.toContain('Retry');
    expect(html).toContain('config_error');
  });

  it('keeps Retry when task recovery_hint is retry', () => {
    learnState.task = makeTask({
      error: 'Task timed out. Try again or increase the timeout.',
      error_code: 'timeout',
      recovery_hint: 'retry',
    });
    learnState.error = 'Task timed out. Try again or increase the timeout.';
    learnState.errorCode = 'timeout';

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    expect(html).toContain('Retry');
  });

  it('renders rate limits without adding a non-V6 clock icon', () => {
    learnState.error = 'rate_limited:60';
    learnState.errorCode = 'rate_limited';

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    expect(html).toContain('Rate limited. Try again in 60 seconds.');
    expect(html).not.toContain('⏱');
  });

  it('renders sub-step message from backend progress.message verbatim', () => {
    learnState.phase = 'running';
    learnState.task = makeTask({
      status: 'running',
      progress: {
        current: 6,
        total: 8,
        message: 'Generating full lesson (1/3)',
        step_started_at: '2026-05-07T00:00:00Z',
      },
      started_at: '2026-05-07T00:00:00Z',
    });

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    // Backend message renders verbatim (no i18n mapping); sub-step "(1/3)" is preserved.
    expect(html).toContain('Generating full lesson (1/3)');
    expect(html).toContain('Step 6/8');
  });

  it('updates sub-step message when backend advances step_started_at', () => {
    learnState.phase = 'running';
    learnState.task = makeTask({
      status: 'running',
      progress: {
        current: 6,
        total: 8,
        message: 'Generating hint lesson (2/3)',
        step_started_at: '2026-05-07T00:01:00Z',
      },
      started_at: '2026-05-07T00:00:00Z',
    });

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    // After backend advances to next sub-step, the new message renders.
    // useElapsed hook resets local timer via [startIso] dep when step_started_at changes.
    expect(html).toContain('Generating hint lesson (2/3)');
    expect(html).not.toContain('Generating full lesson');
  });

  it('renders completed phase with result summary and action buttons', () => {
    learnState.phase = 'completed';
    learnState.task = makeTask({
      status: 'completed',
      result_summary: {
        run_id: 'run-abc',
        status: 'keep',
        overall: 92,
        verdict: 'PASS',
        warnings: [],
      },
    });

    const html = renderToStaticMarkup(<LearnTaskBanner />);

    expect(html).toContain('Learn run completed');
    expect(html).toContain('Dismiss');
    expect(html).toContain('View run');
  });
});
