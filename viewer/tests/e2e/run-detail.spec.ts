import { test, expect } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('Run Detail page', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('renders overview tab with run metadata', async ({ page }) => {
    await page.goto('/#/run/test-run');
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();

    const overviewTab = page.getByRole('tab', { name: /overview|概览/i });
    await expect(overviewTab).toHaveAttribute('aria-selected', 'true');

    const metaRows = page.locator('.run-detail__meta-row');
    expect(await metaRows.count()).toBeGreaterThanOrEqual(4);
  });

  test('renders degraded flags as localized labels', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/run/degraded-run',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'degraded-run',
            source_kind: 'git_ref',
            source_ref: 'HEAD',
            content_lang: 'en',
            capability_level: 2,
            verdict: 'CAUTION',
            overall: 72,
            status: 'baseline',
            weakest_dim: 'diff_coverage',
            created_at: '2026-04-25T00:00:00Z',
            degraded_flags: { diff_clipped: true, file_count_exceeded: true },
            base_ref: 'HEAD~1',
            prompt_version: 'abc1234',
            eval_bundle_version: 'v1',
            note_json: null,
            artifacts: ['patch.diff', 'metadata.json', 'claims.jsonl'],
            graphify_mode: null,
            graphify_status: null,
            graphify_notes: null,
          }),
        }),
    );

    await page.goto('/#/run/degraded-run');

    const flags = page.locator('.run-detail__degraded-list');
    await expect(flags).toContainText('Diff clipped');
    await expect(flags).toContainText('File count exceeded');
    await expect(flags).not.toContainText('diff_clipped');
  });

  test('switches to score tab and shows dimension bars', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await scoreTab.click();
    await expect(scoreTab).toHaveAttribute('aria-selected', 'true');

    const dimRows = page.locator('.score-breakdown__dim-row');
    expect(await dimRows.count()).toBeGreaterThanOrEqual(1);

    const overallValue = page.locator('.score-breakdown__overall-value');
    await expect(overallValue).toBeVisible();
  });

  test('switches to judge tab and shows model info', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const judgeTab = page.getByRole('tab', { name: /judge|评审/i });
    await judgeTab.click();
    await expect(judgeTab).toHaveAttribute('aria-selected', 'true');

    const modelValue = page.locator('.judge-report__model-value');
    await expect(modelValue).toContainText('gpt-5.5');
  });

  test('shows artifact links in artifacts tab', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const artifactsTab = page.getByRole('tab', { name: /artifact|产物/i });
    await artifactsTab.click();

    const links = page.locator('.run-detail__artifact-link');
    expect(await links.count()).toBeGreaterThanOrEqual(2);

    const fileItems = page.locator('.run-detail__artifact-item');
    expect(await fileItems.count()).toBeGreaterThanOrEqual(3);
  });

  test('tab keyboard navigation works with arrow keys', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const overviewTab = page.getByRole('tab', { name: /overview|概览/i });
    await overviewTab.focus();

    await page.keyboard.press('ArrowRight');
    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await expect(scoreTab).toBeFocused();

    await page.keyboard.press('End');
    const artifactsTab = page.getByRole('tab', { name: /artifact|产物/i });
    await expect(artifactsTab).toBeFocused();

    await page.keyboard.press('Home');
    await expect(overviewTab).toBeFocused();
  });

  test('respects tab query param', async ({ page }) => {
    await page.goto('/#/run/test-run?tab=score');

    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await expect(scoreTab).toHaveAttribute('aria-selected', 'true');
  });

  test('loads per-run concepts from concepts tab', async ({ page }) => {
    await page.goto('/#/run/test-run?tab=concepts');

    const conceptsTab = page.getByRole('tab', { name: /concepts|概念/i });
    await expect(conceptsTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('td').filter({ hasText: /^Learn-from-diff$/ })).toBeVisible();
    await expect(page.locator('.run-detail__loading')).toHaveCount(0);
  });

  test('falls back from concepts deep link when run has no concepts artifact', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/run/no-concepts-run',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'no-concepts-run',
            source_kind: 'git_ref',
            source_ref: 'HEAD',
            content_lang: 'en',
            capability_level: 3,
            verdict: 'PASS',
            overall: 88,
            status: 'baseline',
            weakest_dim: 'evidence',
            created_at: '2026-04-25T00:00:00Z',
            degraded_flags: {},
            base_ref: 'HEAD~1',
            prompt_version: 'abc1234',
            eval_bundle_version: 'v1',
            note_json: null,
            artifacts: ['patch.diff', 'metadata.json', 'claims.jsonl', 'score.json'],
            graphify_mode: null,
            graphify_status: null,
            graphify_notes: null,
          }),
        }),
    );

    await page.goto('/#/run/no-concepts-run?tab=concepts');

    const overviewTab = page.getByRole('tab', { name: /overview|概览/i });
    await expect(overviewTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tab', { name: /concepts|概念/i })).toHaveCount(0);
  });

  test('clears stale score data when the next run has no score artifact', async ({ page }) => {
    await page.goto('/#/run/test-run?tab=score');
    await expect(page.locator('.score-breakdown__overall-value')).toBeVisible();

    await page.evaluate(() => {
      window.location.hash = '#/run/no-score-run?tab=score';
    });

    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await expect(scoreTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.score-breakdown__overall-value')).toHaveCount(0);
    await expect(page.locator('.run-detail__empty')).toBeVisible();
  });

  test('same-route tab query changes sync the selected tab', async ({ page }) => {
    await page.goto('/#/run/test-run?tab=judge');
    const judgeTab = page.getByRole('tab', { name: /judge|评审/i });
    await expect(judgeTab).toHaveAttribute('aria-selected', 'true');

    await page.evaluate(() => {
      window.location.hash = '#/run/test-run?tab=score';
    });

    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await expect(scoreTab).toHaveAttribute('aria-selected', 'true');
  });

  test('shows judge unavailable on 404 and error on malformed JSON', async ({ page }) => {
    await page.goto('/#/run/missing-judge?tab=judge');
    await expect(page.getByText(/No judge report|无评审报告/i)).toBeVisible();

    await page.goto('/#/run/invalid-judge?tab=judge');
    await expect(page.getByRole('alert')).toContainText(/Failed to load judge|加载评审报告失败/i);
  });
});
