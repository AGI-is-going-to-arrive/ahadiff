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

    await expect(page.locator('.run-detail__summary-card')).toBeVisible();
    const metaRows = page.locator('.run-detail__meta-row');
    expect(await metaRows.count()).toBeGreaterThanOrEqual(2);
  });

  test('shows Graphify signoff on overview', async ({ page }) => {
    await page.goto('/#/run/test-run');

    await expect(page.getByRole('heading', { name: /Graphify Signoff|Graphify 验收/i })).toBeVisible();
    await expect(page.getByText('Passed', { exact: true })).toBeVisible();
    await expect(page.getByText(/Graph digest|图谱摘要/i)).toBeVisible();
  });

  test('shows degraded Graphify signoff reasons', async ({ page }) => {
    await page.goto('/#/run/degraded-graphify-run');

    await expect(page.getByRole('heading', { name: /Graphify Signoff|Graphify 验收/i })).toBeVisible();
    await expect(page.getByText(/Graph is stale|图谱已过期/i)).toBeVisible();
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

    const flags = page.locator('.run-detail__degraded-banner');
    await expect(flags).toContainText('Diff clipped');
    await expect(flags).toContainText('File count exceeded');
    await expect(flags).not.toContainText('diff_clipped');
  });

  test('switches to score tab and shows dimension bars', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const scoreTab = page.getByRole('tab', { name: /score|评分/i });
    await scoreTab.click();
    await expect(scoreTab).toHaveAttribute('aria-selected', 'true');

    const dimCards = page.locator('.score-breakdown__dim-card');
    expect(await dimCards.count()).toBeGreaterThanOrEqual(1);

    const overallValue = page.locator('.score-breakdown__overall-value');
    await expect(overallValue).toBeVisible();
  });

  test('score tab localizes hard gate names and claim anchor detail', async ({ page }) => {
    await page.goto('/#/run/gate-fail-run?tab=score');

    await expect(page.getByText('claim anchor coverage', { exact: true })).toBeVisible();
    await expect(page.getByText(
      'Claim anchors scored 7.25; this gate requires 8.40.',
      { exact: true },
    )).toBeVisible();
  });

  test('shows spec alignment details in score tab', async ({ page }) => {
    await page.goto('/#/run/test-run?tab=score');

    await expect(page.getByRole('heading', { name: /Spec Alignment|Spec 一致性/i })).toBeVisible();
    await expect(page.locator('.run-detail__spec-score')).toContainText('7.5/10');
    await expect(
      page.locator('.run-detail__spec-requirements').first().getByText('REQ-001'),
    ).toBeVisible();
    await expect(page.getByText(/Verified claim overlaps/i)).toBeVisible();
    await expect(page.getByRole('heading', { name: /Semantic review|语义审查/i })).toBeVisible();
    await expect(page.getByText(/gpt-5\.5/i)).toBeVisible();
    await expect(page.getByText(/Disagrees with deterministic matcher|与确定性 matcher 不一致/i)).toBeVisible();
  });

  test('shows spec alignment missing and bad-artifact states', async ({ page }) => {
    await page.goto('/#/run/missing-spec-run?tab=score');
    await expect(page.getByText(/No spec alignment artifact|没有 Spec 一致性产物/i)).toBeVisible();

    await page.goto('/#/run/invalid-spec-run?tab=score');
    await expect(page.getByRole('alert')).toContainText(
      /Failed to load spec alignment|加载 Spec 一致性失败/i,
    );
  });

  test('shows spec alignment without score data and empty requirements state', async ({ page }) => {
    await page.goto('/#/run/no-score-spec-run?tab=score');
    await expect(page.getByText(/No score data available|无评分数据/i)).toBeVisible();
    await expect(page.getByRole('heading', { name: /Spec Alignment|Spec 一致性/i })).toBeVisible();
    await expect(
      page.locator('.run-detail__spec-requirements').first().getByText('REQ-001'),
    ).toBeVisible();

    await page.goto('/#/run/empty-spec-run?tab=score');
    await expect(
      page.getByText(/No requirements were extracted|未从 Spec 中提取到需求/i),
    ).toBeVisible();
  });

  test('switches to judge tab and shows model info', async ({ page }) => {
    await page.goto('/#/run/test-run');

    const judgeTab = page.getByRole('tab', { name: /judge|评审/i });
    await judgeTab.scrollIntoViewIfNeeded();
    await judgeTab.click();
    await expect(judgeTab).toHaveAttribute('aria-selected', 'true');

    const modelValue = page.locator('.judge-report__model-value');
    await expect(modelValue).toContainText('gpt-5.5');
    await expect(page.locator('.judge-report__summary-value')).toContainText('91.5');
    await expect(page.locator('.judge-report__summary-note')).toContainText('Semantic review result');
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
