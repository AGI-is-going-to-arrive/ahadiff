import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LearnTaskBanner from './LearnTaskBanner';
import type { TaskInfoResponse } from '../api/types';

interface MockLearnState {
  phase: 'idle' | 'submitting' | 'running' | 'completed' | 'cancelled' | 'failed' | 'cancelling';
  task: TaskInfoResponse | null;
  error: string | null;
  errorCode: string | null;
  retryable: boolean;
  cancelLearn: () => void;
  dismiss: () => void;
  retryLearn: () => void;
  recoverExistingTask: () => Promise<void>;
}

const cancelLearn = vi.fn();
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
    progress: { current: 0, total: 0, message: '' },
    created_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

describe('LearnTaskBanner', () => {
  beforeEach(() => {
    learnState = {
      phase: 'failed',
      task: null,
      error: null,
      errorCode: null,
      retryable: true,
      cancelLearn,
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
});
