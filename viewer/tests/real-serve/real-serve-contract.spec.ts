import { expect, test } from '@playwright/test';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SERVE_PORT = 18765;
const HEALTHZ = `http://127.0.0.1:${SERVE_PORT}/healthz`;

let tempRepo = '';
let serveProcess: ChildProcess | null = null;
let serveOutput = '';

function workspaceRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
}

function runGit(cwd: string, args: string[]): void {
  execFileSync('git', args, { cwd, stdio: 'ignore' });
}

function createTempGitRepo(): string {
  const repo = mkdtempSync(path.join(tmpdir(), 'ahadiff-real-serve-'));
  runGit(repo, ['init']);
  runGit(repo, ['config', 'user.email', 'real-serve@example.test']);
  runGit(repo, ['config', 'user.name', 'AhaDiff Real Serve E2E']);
  mkdirSync(path.join(repo, 'src'), { recursive: true });
  writeFileSync(
    path.join(repo, 'src', 'calculator.py'),
    'def add(a, b):\n    return a + b\n',
  );
  runGit(repo, ['add', 'src/calculator.py']);
  runGit(repo, ['commit', '-m', 'initial']);
  writeFileSync(
    path.join(repo, 'src', 'calculator.py'),
    'def add(a, b):\n    total = a + b\n    return total\n',
  );
  return repo;
}

function startServe(repo: string): ChildProcess {
  const child = spawn(
    'uv',
    [
      'run',
      '--frozen',
      '--no-sync',
      'python',
      '-m',
      'ahadiff',
      'serve',
      '--repo-root',
      repo,
      '--port',
      String(SERVE_PORT),
      '--no-browser',
    ],
    {
      cwd: workspaceRoot(),
      env: {
        ...process.env,
        UV_CACHE_DIR: process.env.UV_CACHE_DIR ?? '/tmp/ahadiff-uv-cache',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  child.stdout?.on('data', (chunk: Buffer) => {
    serveOutput += chunk.toString();
  });
  child.stderr?.on('data', (chunk: Buffer) => {
    serveOutput += chunk.toString();
  });
  return child;
}

async function waitForServe(): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (serveProcess?.exitCode !== null) {
      throw new Error(`ahadiff serve exited early:\n${serveOutput}`);
    }
    try {
      const res = await fetch(HEALTHZ);
      if (res.ok) return;
    } catch {
      // Keep polling until uvicorn accepts loopback connections.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`timed out waiting for ahadiff serve:\n${serveOutput}`);
}

async function stopServe(): Promise<void> {
  if (!serveProcess || serveProcess.exitCode !== null) return;
  serveProcess.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => serveProcess?.once('exit', resolve)),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  if (serveProcess.exitCode === null) serveProcess.kill('SIGKILL');
}

test.beforeAll(async () => {
  tempRepo = createTempGitRepo();
  serveProcess = startServe(tempRepo);
  await waitForServe();
});

test.afterAll(async () => {
  await stopServe();
  if (tempRepo) rmSync(tempRepo, { recursive: true, force: true });
});

test('browser calls real serve token, estimate, task, and progress stream', async ({ page }) => {
  await page.goto('/');

  const result = await page.evaluate(async () => {
    const tokenRes = await fetch('/api/auth/token', {
      method: 'POST',
      credentials: 'same-origin',
    });
    const tokenBody = await tokenRes.json();
    const token = typeof tokenBody.token === 'string' ? tokenBody.token : '';
    const headers = {
      'content-type': 'application/json',
      'X-AhaDiff-Token': token,
    };
    const learnPayload = {
      unstaged: true,
      include_untracked: true,
      dry_run: true,
      force_learn: true,
    };

    const serveStatusRes = await fetch('/api/serve/status', { credentials: 'same-origin' });
    const serveStatus = await serveStatusRes.json();
    const estimateRes = await fetch('/api/learn/estimate', {
      method: 'POST',
      headers,
      credentials: 'same-origin',
      body: JSON.stringify(learnPayload),
    });
    const estimate = await estimateRes.json();
    const submitRes = await fetch('/api/learn', {
      method: 'POST',
      headers,
      credentials: 'same-origin',
      body: JSON.stringify(learnPayload),
    });
    const submit = await submitRes.json();
    const taskId = typeof submit.task_id === 'string' ? submit.task_id : '';

    let task: Record<string, unknown> | null = null;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const taskRes = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
        credentials: 'same-origin',
      });
      task = await taskRes.json();
      if (task === null) continue;
      if (
        task.status === 'completed' ||
        task.status === 'failed' ||
        task.status === 'cancelled'
      ) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }

    const streamRes = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/progress`, {
      credentials: 'same-origin',
    });
    const streamText = await streamRes.text();

    return {
      tokenStatus: tokenRes.status,
      hasToken: token.length > 12,
      serveStatusCode: serveStatusRes.status,
      serveStatus,
      estimateStatus: estimateRes.status,
      estimate,
      submitStatus: submitRes.status,
      submit,
      task,
      streamStatus: streamRes.status,
      streamText,
    };
  });

  expect(result.tokenStatus).toBe(200);
  expect(result.hasToken).toBe(true);
  expect(result.serveStatusCode).toBe(200);
  expect(result.serveStatus.version).toEqual(expect.any(String));
  expect(result.serveStatus.uptime_seconds).toBeGreaterThanOrEqual(0);
  expect(result.estimateStatus).toBe(200);
  expect(result.estimate).toMatchObject({ risk_level: 'ok' });
  expect(result.estimate.patch_bytes).toBeGreaterThan(0);
  expect(result.submitStatus).toBe(202);
  expect(result.submit.task_id).toEqual(expect.any(String));
  expect(result.task).toMatchObject({
    task_id: result.submit.task_id,
    task_type: 'learn',
    status: 'completed',
  });
  expect(result.task?.result_summary).toMatchObject({ status: 'dry_run' });
  expect(result.streamStatus).toBe(200);
  expect(result.streamText).toContain('event: progress');
  expect(result.streamText).toContain('"status": "completed"');
});

test('browser renders core pages against real serve APIs without mocks', async ({ page }) => {
  await page.goto('/#/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('[role="alert"]')).toHaveCount(0);

  await page.goto('/#/guide');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('.guide-agent-card')).toHaveCount(13);
  await expect(page.locator('[role="alert"]')).toHaveCount(0);

  await page.goto('/#/concepts?tab=graph');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
});
