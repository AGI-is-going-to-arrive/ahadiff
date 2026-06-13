import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

const TASK_ID = 'task-e2e-learn-001';

interface LearnMockCalls {
  estimate: number;
  submit: number;
  task: number;
  cancel: number;
  list: number;
}

function makeTaskInfo(overrides: Record<string, unknown> = {}) {
  return {
    task_id: TASK_ID,
    task_type: 'learn',
    status: 'running',
    progress: { current: 0, total: 10, message: '' },
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

async function installLearnMocks(
  page: Page,
  opts: {
    submitStatus?: number;
    submitBody?: unknown;
    taskSequence?: Array<Record<string, unknown>>;
    cancelOk?: boolean;
    listTasks?: unknown[];
    estimateRiskLevel?: 'ok' | 'warn' | 'danger';
    estimateWarnings?: string[];
    progressSequence?: Array<Record<string, unknown>>;
  } = {},
): Promise<LearnMockCalls> {
  const {
    submitStatus = 202,
    submitBody = { task_id: TASK_ID },
    taskSequence = [],
    cancelOk = true,
    listTasks = [],
    estimateRiskLevel = 'ok',
    estimateWarnings = [],
    progressSequence,
  } = opts;

  let pollIndex = 0;
  const calls: LearnMockCalls = { estimate: 0, submit: 0, task: 0, cancel: 0, list: 0 };

  // Mock estimate endpoint; warning tests can force the preflight branch.
  await page.route(
    (url) => url.pathname === '/api/learn/estimate',
    (route) => {
      if (route.request().method() !== 'POST') {
        return route.fulfill({ status: 405, contentType: 'application/json', body: '{}' });
      }
      calls.estimate += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          patch_bytes: 1024,
          file_count: 3,
          total_lines: 50,
          estimated_tokens: 2000,
          provider_context_window: 128000,
          provider_max_output: 8192,
          risk_level: estimateRiskLevel,
          warnings: estimateWarnings,
        }),
      });
    },
  );

  await page.route(
    (url) => url.pathname === '/api/learn',
    (route) => {
      if (route.request().method() !== 'POST') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      calls.submit += 1;
      return route.fulfill({
        status: submitStatus,
        contentType: 'application/json',
        body: JSON.stringify(submitBody),
      });
    },
  );

  await page.route(
    (url) => /^\/api\/tasks\/[^/]+$/.test(url.pathname) && !url.pathname.endsWith('/cancel'),
    (route) => {
      if (route.request().method() !== 'GET') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      calls.task += 1;
      const info = pollIndex < taskSequence.length
        ? makeTaskInfo(taskSequence[pollIndex++]!)
        : makeTaskInfo(taskSequence[taskSequence.length - 1] ?? {});
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(info),
      });
    },
  );

  await page.route(
    (url) => /^\/api\/tasks\/[^/]+\/progress$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== 'GET') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      const events = progressSequence ?? [];
      const body = events.length === 0
        ? 'event: error\n' +
          'data: {"event":"error","data":{"error":"progress stream unavailable"}}\n\n'
        : events
          .map((event) => {
            const info = makeTaskInfo(event);
            return `event: progress\ndata: ${JSON.stringify({ event: 'progress', data: info })}\n\n`;
          })
          .join('');
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      });
    },
  );

  await page.route(
    (url) => /^\/api\/tasks\/[^/]+\/cancel$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== 'POST') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      calls.cancel += 1;
      return route.fulfill({
        status: cancelOk ? 200 : 404,
        contentType: 'application/json',
        body: JSON.stringify(cancelOk ? { cancelled: true } : { error: 'not found' }),
      });
    },
  );

  await page.route(
    (url) => url.pathname === '/api/tasks',
    (route) => {
      if (route.request().method() !== 'GET') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      calls.list += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tasks: listTasks }),
      });
    },
  );

  return calls;
}

/** Click "Learn Run" in topbar, wait for the LearnModeDialog, then click "Start Run". */
async function triggerLearnViaDialog(page: Page): Promise<void> {
  const learnBtn = page.getByRole('button', { name: 'Start a new learn run', exact: true });
  await learnBtn.click();
  // Wait for dialog to appear
  const dialog = page.locator('[role="dialog"]');
  await expect(dialog).toBeVisible({ timeout: 5000 });
  // Click "Start Run" in the dialog (default mode = working)
  const startBtn = dialog.locator('.learn-dialog__btn--primary');
  await startBtn.click();
  // Dialog closes
  await expect(dialog).not.toBeVisible({ timeout: 3000 });
}

async function triggerLearnViaWelcome(page: Page): Promise<void> {
  const learnBtn = page.getByRole('button', {
    name: /Start from your diff|从你的 diff 开始/,
  });
  const dialog = page.getByRole('dialog');
  await expect(learnBtn).toBeVisible();
  await expect(learnBtn).toBeEnabled();
  await expect(async () => {
    if (!(await dialog.isVisible().catch(() => false))) {
      await learnBtn.click();
    }
    await expect(dialog).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 10000 });
  await dialog.locator('.learn-dialog__btn--primary').click();
  await expect(dialog).not.toBeVisible({ timeout: 3000 });
}

test.describe('learn task flow', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('happy path: submit → running → completed', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 3, total: 10, message: 'Extracting claims' } },
        { status: 'running', progress: { current: 7, total: 10, message: 'Generating lesson' } },
        {
          status: 'completed',
          progress: { current: 10, total: 10, message: 'Done' },
          result_summary: { run_id: 'run-001', status: 'completed', overall: 92, verdict: 'PASS', warnings: [] },
        },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toBeVisible();

    await expect(banner.locator('.learn-banner__bar-fill')).toBeVisible();

    await expect(banner).toHaveClass(/learn-banner--completed/);
    await expect(banner.locator('.verdict-badge')).toBeVisible();
    await expect(banner.locator('.learn-banner__score')).toContainText('92');

    const viewLink = banner.locator('a:has-text("View run"), a:has-text("查看运行")');
    await expect(viewLink).toBeVisible();
    await expect(viewLink).toHaveAttribute('href', '#/run/run-001/lesson');
    expect(calls.submit).toBe(1);
    expect(calls.task).toBeGreaterThan(0);

    await banner.locator('button:has-text("Dismiss"), button:has-text("关闭")').click();
    await expect(banner).not.toBeVisible();
  });

  test('welcome CTA shows learn task feedback after submit', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 4, total: 10, message: 'Creating lesson' } },
      ],
    });
    await page.goto('/#/welcome');

    await triggerLearnViaWelcome(page);

    const banner = page.locator('.hero-learn-status .learn-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveClass(/learn-banner--running/);
    await expect(banner.locator('.learn-banner__bar-track')).toBeVisible();
    expect(calls.submit).toBe(1);
  });

  test('welcome preview switches from example to completed run artifacts', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/run/run-live/diff',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'run-live',
            artifact_type: 'diff',
            content: 'diff --git a/real.py b/real.py\n+real completed diff\n',
            content_lang: 'en',
          }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/run/run-live/lesson',
      (route) => {
        const level = new URL(route.request().url()).searchParams.get('level');
        if (level === 'compact') {
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              run_id: 'run-live',
              artifact_type: 'lesson',
              content: '## Real completed lesson\n\nThis came from the finished Learn run.',
              content_lang: 'en',
            }),
          });
        }
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found' }),
        });
      },
    );
    await installLearnMocks(page, {
      progressSequence: [
        {
          status: 'completed',
          progress: { current: 10, total: 10, message: 'Done' },
          result_summary: {
            run_id: 'run-live',
            status: 'completed',
            overall: 88,
            verdict: 'PASS',
            warnings: [],
          },
        },
      ],
    });
    await page.goto('/#/welcome');

    await triggerLearnViaWelcome(page);

    const banner = page.locator('.hero-learn-status .learn-banner');
    await expect(banner).toHaveClass(/learn-banner--completed/);
    await expect(page.locator('.hero-demo__source')).toContainText(/Latest finalized run|最新完成运行/);
    await expect(page.locator('#demo-panel')).toContainText('Real completed lesson');
    await expect(page.locator('.ba-grid')).toContainText('real completed diff');
    await expect(page.locator('.ba-grid')).toContainText('Real completed lesson');
  });

  test('welcome preview never mixes sample lesson into a completed run', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/run/run-skip/diff',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'run-skip',
            artifact_type: 'diff',
            content: 'diff --git a/skip.py b/skip.py\n+real skipped lesson diff\n',
            content_lang: 'en',
          }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/run/run-skip/lesson',
      (route) =>
        route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found' }),
        }),
    );
    await installLearnMocks(page, {
      progressSequence: [
        {
          status: 'completed',
          progress: { current: 10, total: 10, message: 'Done' },
          result_summary: {
            run_id: 'run-skip',
            status: 'completed',
            overall: 88,
            verdict: 'PASS',
            warnings: [],
          },
        },
      ],
    });
    await page.goto('/#/welcome');

    await triggerLearnViaWelcome(page);

    const banner = page.locator('.hero-learn-status .learn-banner');
    await expect(banner).toHaveClass(/learn-banner--completed/);
    await expect(page.locator('.hero-demo__source')).toContainText(/Latest finalized run|最新完成运行/);
    await expect(page.locator('#demo-panel')).toContainText(
      /No lesson was generated for this run|这次运行没有生成课程/,
    );
    await expect(page.locator('#demo-panel')).not.toContainText('The return value was updated');
    await expect(page.locator('.ba-grid')).toContainText('real skipped lesson diff');
    await expect(page.locator('.ba-grid')).toContainText(
      /No lesson was generated for this run|这次运行没有生成课程/,
    );
    await expect(page.locator('.ba-grid')).not.toContainText('The return value was updated');
    await expect(page.locator('.hero-demo__lesson-link')).toContainText(/View run detail|查看运行详情/);
  });

  test('welcome preview keeps real run context when lesson artifact fails', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/run/run-artifact-error/diff',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'run-artifact-error',
            artifact_type: 'diff',
            content: 'diff --git a/fragile.py b/fragile.py\n+real fragile diff\n',
            content_lang: 'en',
          }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/run/run-artifact-error/lesson',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'internal_error' }),
        }),
    );
    await installLearnMocks(page, {
      progressSequence: [
        {
          status: 'completed',
          progress: { current: 10, total: 10, message: 'Done' },
          result_summary: {
            run_id: 'run-artifact-error',
            status: 'completed',
            overall: 88,
            verdict: 'PASS',
            warnings: [],
          },
        },
      ],
    });
    await page.goto('/#/welcome');

    await triggerLearnViaWelcome(page);

    await expect(page.locator('.hero-demo__source')).toContainText(/Latest finalized run|最新完成运行/);
    await expect(page.locator('#demo-panel')).toContainText(
      /No lesson was generated for this run|这次运行没有生成课程/,
    );
    await expect(page.locator('#demo-panel')).not.toContainText('The return value was updated');
    await expect(page.locator('.ba-grid')).toContainText('real fragile diff');
    await expect(page.locator('.ba-grid')).not.toContainText('The return value was updated');
  });

  test('cancel running task', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 2, total: 10, message: 'Working' } },
        { status: 'running', progress: { current: 4, total: 10, message: 'Working' } },
        { status: 'cancelled' },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);
    const banner = page.locator('.learn-banner');
    await expect(banner).toBeVisible();

    const cancelBtn = banner.locator('.learn-banner__btn--cancel');
    await expect(cancelBtn).toBeVisible();
    await cancelBtn.click();

    await expect(banner).toHaveClass(/learn-banner--cancelled/);
    expect(calls.cancel).toBe(1);
  });

  test('submit failure shows error banner with retry', async ({ page }) => {
    await installLearnMocks(page, {
      submitStatus: 500,
      submitBody: { error: 'internal_error', status: 500 },
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toHaveClass(/learn-banner--failed/);
    await expect(banner.locator('.learn-banner__btn--retry')).toBeVisible();
    await expect(banner.locator('.learn-banner__btn--dismiss')).toBeVisible();
  });

  test('503 too_many_pending shows friendly message', async ({ page }) => {
    await installLearnMocks(page, {
      submitStatus: 503,
      submitBody: { error: 'too_many_pending_learn_tasks', status: 503 },
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toHaveClass(/learn-banner--failed/);
    await expect(banner.locator('.learn-banner__icon')).toContainText('⏳');
  });

  test('progress bar updates aria-valuenow', async ({ page }) => {
    await installLearnMocks(page, {
      progressSequence: [
        { status: 'running', progress: { current: 5, total: 10, message: 'Halfway' } },
      ],
      taskSequence: [
        { status: 'running', progress: { current: 0, total: 10, message: 'Starting' } },
        { status: 'running', progress: { current: 5, total: 10, message: 'Halfway' } },
        { status: 'running', progress: { current: 10, total: 10, message: 'Finishing' } },
        { status: 'completed', result_summary: { run_id: 'r1', overall: 90, verdict: 'PASS', warnings: [] } },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const bar = page.locator('.learn-banner__bar-track');
    await expect(bar).toBeVisible();

    await expect(bar).toHaveAttribute('aria-valuenow', '50', { timeout: 5000 });
  });

  test('warn estimate shows preflight and continue submits once', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      estimateRiskLevel: 'warn',
      estimateWarnings: ['Large patch may be clipped'],
      taskSequence: [
        { status: 'running', progress: { current: 1, total: 10, message: 'Starting' } },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveClass(/learn-banner--confirming/);
    await expect(banner.locator('.learn-banner__risk')).toHaveClass(/learn-banner__risk--warn/);
    await expect(banner).toContainText('Large diff detected');
    await expect(banner).toContainText('Large patch may be clipped');
    expect(calls.submit).toBe(0);

    await banner.locator('button:has-text("Continue anyway")').click();
    await expect(banner).toHaveClass(/learn-banner--running/);
    expect(calls.submit).toBe(1);
  });

  test('danger estimate can be cancelled without submitting', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      estimateRiskLevel: 'danger',
      estimateWarnings: ['Provider context window may be exceeded'],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveClass(/learn-banner--confirming/);
    await expect(banner.locator('.learn-banner__risk')).toHaveClass(/learn-banner__risk--danger/);
    await expect(banner).toContainText('Provider context window may be exceeded');
    expect(calls.submit).toBe(0);

    await banner.locator('button:has-text("Cancel")').click();
    await expect(banner).not.toBeVisible();
    expect(calls.submit).toBe(0);
  });

  test('task recovery on page load', async ({ page }) => {
    const activeTask = makeTaskInfo({ status: 'running', progress: { current: 3, total: 10, message: 'Recovering' } });
    await installLearnMocks(page, {
      listTasks: [activeTask],
      taskSequence: [
        { status: 'running', progress: { current: 5, total: 10, message: 'Continuing' } },
        { status: 'completed', result_summary: { run_id: 'r2', overall: 85, verdict: 'PASS', warnings: [] } },
      ],
    });
    await page.goto('/');

    const banner = page.locator('.learn-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveClass(/learn-banner--running|learn-banner--completed/);
  });

  test('dismiss clears banner completely', async ({ page }) => {
    await installLearnMocks(page, {
      taskSequence: [
        { status: 'failed', error: 'Something broke', error_code: 'internal_error' },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const banner = page.locator('.learn-banner');
    await expect(banner).toHaveClass(/learn-banner--failed/);

    await banner.locator('.learn-banner__btn--dismiss').click();
    await expect(banner).not.toBeVisible();

    await triggerLearnViaDialog(page);
    await expect(banner).toBeVisible();
  });

  test('topbar button shows busy class during active task', async ({ page }) => {
    await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 5, total: 10, message: 'Working' } },
      ],
    });
    await page.goto('/');

    await triggerLearnViaDialog(page);

    const primaryBtn = page.locator('.topbar__btn--primary');
    await expect(primaryBtn).toHaveClass(/topbar__btn--busy/);
    await expect(primaryBtn).toBeDisabled();
  });
});
