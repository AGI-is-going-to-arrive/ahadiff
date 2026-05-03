import { expect, test, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

const TASK_ID = 'task-e2e-learn-001';

interface LearnMockCalls {
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
  } = {},
): Promise<LearnMockCalls> {
  const {
    submitStatus = 202,
    submitBody = { task_id: TASK_ID },
    taskSequence = [],
    cancelOk = true,
    listTasks = [],
  } = opts;

  let pollIndex = 0;
  const calls: LearnMockCalls = { submit: 0, task: 0, cancel: 0, list: 0 };

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

    const learnBtn = page.locator('button:has-text("Learn Run")');
    await learnBtn.click();

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

  test('cancel running task', async ({ page }) => {
    const calls = await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 2, total: 10, message: 'Working' } },
        { status: 'running', progress: { current: 4, total: 10, message: 'Working' } },
        { status: 'cancelled' },
      ],
    });
    await page.goto('/');

    await page.locator('button:has-text("Learn Run")').click();
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

    await page.locator('button:has-text("Learn Run")').click();

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

    await page.locator('button:has-text("Learn Run")').click();

    const banner = page.locator('.learn-banner');
    await expect(banner).toHaveClass(/learn-banner--failed/);
    await expect(banner.locator('.learn-banner__icon')).toContainText('⏳');
  });

  test('progress bar updates aria-valuenow', async ({ page }) => {
    await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 0, total: 10, message: 'Starting' } },
        { status: 'running', progress: { current: 5, total: 10, message: 'Halfway' } },
        { status: 'running', progress: { current: 10, total: 10, message: 'Finishing' } },
        { status: 'completed', result_summary: { run_id: 'r1', overall: 90, verdict: 'PASS', warnings: [] } },
      ],
    });
    await page.goto('/');

    await page.locator('button:has-text("Learn Run")').click();

    const bar = page.locator('.learn-banner__bar-track');
    await expect(bar).toBeVisible();

    await expect(bar).toHaveAttribute('aria-valuenow', '50', { timeout: 5000 });
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

    await page.locator('button:has-text("Learn Run")').click();

    const banner = page.locator('.learn-banner');
    await expect(banner).toHaveClass(/learn-banner--failed/);

    await banner.locator('.learn-banner__btn--dismiss').click();
    await expect(banner).not.toBeVisible();

    await page.locator('button:has-text("Learn Run")').click();
    await expect(banner).toBeVisible();
  });

  test('topbar button shows busy class during active task', async ({ page }) => {
    await installLearnMocks(page, {
      taskSequence: [
        { status: 'running', progress: { current: 5, total: 10, message: 'Working' } },
      ],
    });
    await page.goto('/');

    const primaryBtn = page.locator('.topbar__btn--primary');
    await primaryBtn.click();

    await expect(primaryBtn).toHaveClass(/topbar__btn--busy/);
    await expect(primaryBtn).toBeDisabled();
  });
});
