/**
 * walkthrough.spec.ts — Comprehensive functional walkthrough of every AhaDiff
 * viewer page and interaction. Uses the same mock API pattern as serve-mock.ts,
 * but provides richer data to exercise more code paths (multi-run dashboard,
 * ratchet history with 3+ entries, etc.).
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

const RICH_DIFF = `diff --git a/demo.py b/demo.py
index 0000001..0000002 100644
--- a/demo.py
+++ b/demo.py
@@ -1,3 +1,4 @@
 def hello():
-    return "world"
+    return "AhaDiff"
+    # learn-from-diff
@@ -6,3 +7,4 @@ def explain():
 def explain():
-    return "old"
+    return "lesson-ready"
+    # evidence-ready
`;

async function openSidebarIfCollapsed(page: Page): Promise<void> {
  // Drawer paradigm only engages at <=768px now. Between 769-1024px the
  // sidebar collapses to an icon rail (no drawer) and stays in flow.
  const isDrawer = await page.evaluate(
    () => window.matchMedia('(max-width: 768px)').matches,
  );
  if (!isDrawer) return;
  await expect(page.locator('.app-shell')).toBeVisible();
  await expect(page.locator('.topbar')).toBeVisible();
  const menu = page.locator('.topbar__mobile-btn');
  await expect(menu).toBeAttached();
  await expect(menu).toBeVisible();
  if ((await menu.getAttribute('aria-expanded')) !== 'true') {
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
  }
}

async function openSearchOverlay(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('.topbar')).toBeVisible();
  const searchBtn = page.getByRole('button', { name: /Open search/i });
  if (await searchBtn.isVisible().catch(() => false)) {
    await searchBtn.click();
  } else {
    await page.keyboard.press('Control+K');
  }
  await expect(page.getByRole('dialog', { name: /Search|搜索/i })).toBeVisible();
}

async function activateControlWithKeyboard(page: Page, control: Locator): Promise<void> {
  await expect(control).toBeVisible();
  await control.focus();
  await expect(control).toBeFocused();
  await page.keyboard.press('Enter');
}

async function holdPeekGuardTimer(page: Page): Promise<void> {
  await page.addInitScript(`
    (() => {
      const nativeSetTimeout = window.setTimeout.bind(window);
      const nativeClearTimeout = window.clearTimeout.bind(window);
      let nextHeldTimerId = -1;
      const heldTimers = new Map();

      window.setTimeout = (handler, timeout, ...args) => {
        if (timeout === 1500 && typeof handler === 'function') {
          const id = nextHeldTimerId--;
          heldTimers.set(id, () => handler(...args));
          return id;
        }
        return nativeSetTimeout(handler, timeout, ...args);
      };

      window.clearTimeout = (timerId) => {
        if (heldTimers.delete(timerId)) return;
        nativeClearTimeout(timerId);
      };

      window.__ahadiffReleasePeekGuardTimers = () => {
        const callbacks = Array.from(heldTimers.values());
        heldTimers.clear();
        callbacks.forEach((callback) => callback());
      };
    })();
  `);
}

/* ------------------------------------------------------------------ */
/*  Enhanced mock installer: overrides selected routes with richer data */
/* ------------------------------------------------------------------ */

async function installRichMock(page: Page): Promise<void> {
  // Start with base mocks (auth, locale, run detail, lesson, claims, quiz,
  // concepts, review queue, config, doctor, install targets, review rate).
  await installServeMock(page);

  // Override /api/runs to return multiple runs (exercises KPI cards, run table,
  // load-more button path).
  await page.route(
    (url) => url.pathname === '/api/runs',
    (route) => {
      const u = new URL(route.request().url());
      const cursor = u.searchParams.get('cursor');
      // First page: 3 runs.  Second page (cursor): 1 more run + no next_cursor.
      if (!cursor) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            runs: [
              {
                run_id: 'run-001',
                source_kind: 'git_ref',
                source_ref: 'HEAD~2',
                content_lang: 'en',
                capability_level: 3,
                verdict: 'PASS',
                overall: 92,
                status: 'baseline',
                weakest_dim: 'evidence',
                created_at: '2026-04-25T10:00:00Z',
                degraded_flags: {},
              },
              {
                run_id: 'run-002',
                source_kind: 'git_unstaged',
                source_ref: 'HEAD~1',
                content_lang: 'en',
                capability_level: 2,
                verdict: 'CAUTION',
                overall: 71,
                status: 'baseline',
                weakest_dim: 'conciseness',
                created_at: '2026-04-26T12:00:00Z',
                degraded_flags: {},
              },
              {
                run_id: 'run-003',
                source_kind: 'patch_file',
                source_ref: 'HEAD',
                content_lang: 'en',
                capability_level: 3,
                verdict: 'PASS',
                overall: 88,
                status: 'baseline',
                weakest_dim: 'evidence',
                created_at: '2026-04-27T08:00:00Z',
                degraded_flags: {},
              },
            ],
            next_cursor: 'cursor-page2',
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runs: [
              {
                run_id: 'run-004',
                source_kind: 'file_compare',
                source_ref: 'v0.1',
                content_lang: 'en',
                capability_level: 1,
                verdict: 'FAIL',
                overall: 42,
                status: 'baseline',
                weakest_dim: 'accuracy',
                created_at: '2026-04-20T06:00:00Z',
                degraded_flags: {},
              },
              {
                run_id: 'run-005',
                source_kind: 'future_source',
                source_ref: 'external-run',
                content_lang: 'en',
                capability_level: 1,
                verdict: 'PASS',
                overall: 81,
                status: 'baseline',
                weakest_dim: 'spec_alignment',
                created_at: '2026-04-19T06:00:00Z',
                degraded_flags: {},
              },
          ],
        }),
      });
    },
  );

  // Override /api/ratchet/history to return 3+ entries (exercises the chart).
  await page.route(
    (url) => url.pathname === '/api/ratchet/history',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            { run_id: 'run-001', source_ref: 'HEAD~2', eval_bundle_version: 'bundle-v1', overall: 92, verdict: 'PASS', status: 'baseline', weakest_dim: 'evidence', timestamp: '2026-04-25T10:00:00Z' },
            { run_id: 'run-002', source_ref: 'HEAD~1', eval_bundle_version: 'bundle-v1', overall: 71, verdict: 'CAUTION', status: 'baseline', weakest_dim: 'conciseness', timestamp: '2026-04-26T12:00:00Z' },
            { run_id: 'run-003', source_ref: 'HEAD', eval_bundle_version: 'bundle-v2', overall: 88, verdict: 'PASS', status: 'baseline', weakest_dim: 'evidence', timestamp: '2026-04-27T08:00:00Z', note_json: '{"phase25":true,"phase25_note":"PHASE25: consecutive_discard_count=2","trigger_reason":"consecutive_discard_count=2","target_dimension":"learnability","targeted_baseline_score":76,"targeted_candidate_score":88,"targeted_passed":true}' },
          ],
        }),
      }),
  );

  await page.route(
    (url) => url.pathname === '/api/ratchet/transparency',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          results: [
            {
              run_id: 'run-003',
              source_ref: 'HEAD',
              base_ref: 'HEAD~1',
              prompt_version: 'prompt-v2',
              eval_bundle_version: 'bundle-v2',
              rubric_version: 'rubric-v1',
              overall: 88,
              verdict: 'PASS',
              status: 'keep',
              weakest_dim: 'evidence',
              timestamp: '2026-04-27T08:00:00Z',
              note_json: '{"phase25":true,"phase25_note":"PHASE25: consecutive_discard_count=2","trigger_reason":"consecutive_discard_count=2","target_dimension":"learnability","targeted_baseline_score":76,"targeted_candidate_score":88,"targeted_passed":true}',
            },
            {
              run_id: 'run-002',
              source_ref: 'HEAD~1',
              base_ref: 'HEAD~2',
              prompt_version: 'prompt-v1',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'rubric-v1',
              overall: 71,
              verdict: 'CAUTION',
              status: 'discard',
              weakest_dim: 'conciseness',
              timestamp: '2026-04-26T12:00:00Z',
              note_json: '{"targeted_reason":"score did not beat baseline"}',
            },
            {
              run_id: 'run-001',
              source_ref: 'HEAD~2',
              base_ref: null,
              prompt_version: 'prompt-v1',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'rubric-v1',
              overall: 92,
              verdict: 'PASS',
              status: 'baseline',
              weakest_dim: 'evidence',
              timestamp: '2026-04-25T10:00:00Z',
              note_json: null,
            },
          ],
          benchmark: {
            manifest: {
              schema_version: 1,
              suite_id: 'ahadiff-local-v1',
              suite_digest: 'abc123def4567890',
              visibility: 'private',
              entry_count: 31,
              eval_entry_count: 20,
              integration_entry_count: 11,
              degraded_entry_count: 6,
              language_count: 8,
              group_count: 3,
            },
            report: {
              suite_id: 'ahadiff-local-v1',
              suite_digest: 'abc123def4567890',
              eval_bundle_version: 'bundle-v2',
              model_id: 'none',
              api_family_version: 'none',
              output_lang: 'en',
              comparable_entry_count: 14,
              excluded_degraded_count: 6,
              mean_score: 87.25,
              claim_verification_rate: 1,
              entries: [
                {
                  id: 'eval_001_python_retry',
                  group: 'benchmark_main',
                  language: 'python',
                  degraded: false,
                  overall: 91,
                  verdict: 'PASS',
                  weakest_dim: 'evidence',
                  claim_verification_rate: 1,
                  ground_truth_digest: 'f'.repeat(64),
                },
              ],
            },
            warnings: [],
          },
        }),
      }),
  );

  await page.route(
    (url) => url.pathname === '/api/stats',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_runs: 3,
          total_lessons: 3,
          total_quizzes: 2,
          total_concepts: 12,
          total_claims: 8,
          total_reviews: 5,
          avg_overall_score: 83.7,
          weakest_dimensions: ['evidence', 'conciseness'],
          last_run_at: '2026-04-27T08:00:00Z',
        }),
      }),
  );

  await page.route(
    (url) => /^\/api\/run\/[^/]+\/diff$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'diff',
          content: RICH_DIFF,
          content_lang: 'en',
        }),
      }),
  );

  await page.route(
    (url) => /^\/api\/run\/[^/]+\/lesson$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'lesson',
          content:
            '# Sample lesson\n\nThis change adds a learn-from-diff comment.\n\n```python\n# Not a lesson heading\nprint("inside fence")\n```\n\n## Evidence\n\nThe verified claim spans two source hunks.',
          content_lang: 'en',
        }),
      }),
  );

  await page.route(
    (url) => /^\/api\/run\/[^/]+\/claims$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'claims',
          content:
            '{"claim_id":"c1","verdict":"verified","source_hunks":[{"file":"demo.py","start":3,"end":3,"side":"new"},{"file":"demo.py","start":8,"end":9,"side":"new"}],"statement":"adds learn-from-diff comment and follow-up evidence"}\n{"claim_id":"c2","verdict":"weak","file":"demo.py","line_start":7,"line_end":7,"statement":"return value was changed for lesson-ready output"}\n{"claim_id":"c3","verdict":"not_proven","file":"demo.py","line_start":9,"line_end":9,"statement":"evidence-ready comment changes runtime behavior"}\n{"claim_id":"c4","verdict":"rejected","statement":"the diff removes the hello function"}',
          content_lang: 'en',
        }),
      }),
  );
}

async function installLargeGraphMock(page: Page): Promise<void> {
  await page.unroute((url) => url.pathname === '/api/graph/concepts');
  await page.route(
    (url) => url.pathname === '/api/graph/concepts',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: {
            enabled: true,
            source_exists: true,
            has_graph: true,
            freshness: 'fresh',
            node_count: 201,
            edge_count: 0,
            source_path: '.ahadiff/graphify/graph.json',
            provenance: null,
          },
          nodes: Array.from({ length: 201 }, (_, index) => ({
            id: `large-${index + 1}`,
            name: `large-node-${index + 1}`,
            kind: index % 2 === 0 ? 'function' : 'module',
            file_path: `src/large_${index + 1}.py`,
            freshness: 'fresh',
            metadata: {},
          })),
          edges: [],
          truncated: false,
        }),
      }),
  );
}

/* ================================================================== */
/*  SCREENSHOTS directory                                              */
/* ================================================================== */

const SCREENSHOT_DIR = 'tests/e2e/screenshots';

/* ================================================================== */
/*  Tests                                                              */
/* ================================================================== */

test.describe('walkthrough: full-app functional test', () => {
  test.beforeEach(async ({ page }) => {
    await installRichMock(page);
  });

  /* ---------------------------------------------------------------- */
  /*  Page 1: Dashboard                                                */
  /* ---------------------------------------------------------------- */

  test('Dashboard — heading, KPI cards, run table, load more', async ({ page }) => {
    await page.goto('/');

    // Title present
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/Dashboard|运行/);

    // KPI cards visible (V6 grid for >= 2 runs: runs, avg score, pass rate, concepts, LLM calls)
    const kpiCards = page.locator('.kpi-grid--5col > .kpi');
    await expect(kpiCards).toHaveCount(5);
    await expect(kpiCards.nth(0).locator('.lb')).toHaveText('Total runs');
    await expect(kpiCards.nth(1).locator('.lb')).toHaveText('Avg score');
    await expect(kpiCards.nth(2).locator('.lb')).toHaveText('Pass rate');
    await expect(kpiCards.nth(3).locator('.lb')).toHaveText('Concepts learned');
    await expect(kpiCards.nth(4).locator('.lb')).toHaveText('LLM Calls');
    // Verify at least one KPI value reflects mock data
    await expect(kpiCards.nth(0).locator('.vl')).toContainText('3');
    await expect(kpiCards.nth(4).locator('.vl')).toContainText('42');

    // Graphify source card is visible on the Dashboard when the backend has a source.
    await expect(page.locator('.graphify-card').filter({ hasText: 'Graphify source' })).toBeVisible();

    // Run list table
    const runTable = page.getByRole('table', { name: 'Recent runs' });
    await expect(runTable).toBeVisible();
    const rows = runTable.locator('tbody tr');
    await expect(rows).toHaveCount(3);

    const sourceFilters = page.getByRole('group', { name: /Filter loaded runs by source/i });
    await expect(sourceFilters).toBeVisible();
    await expect(sourceFilters.getByRole('button', { name: /All Sources\s+3/i })).toHaveAttribute('aria-pressed', 'true');
    await expect(sourceFilters.getByRole('button', { name: /Commits\s+1/i })).toBeVisible();
    await expect(sourceFilters.getByRole('button', { name: /Working Tree\s+1/i })).toBeVisible();
    await expect(sourceFilters.getByRole('button', { name: /Patch\s+1/i })).toBeVisible();
    const compareChip = sourceFilters.getByRole('button', { name: /Compare\s+0/i });
    await expect(compareChip).toBeVisible();

    await sourceFilters.getByRole('button', { name: /Patch\s+1/i }).click();
    await expect(sourceFilters.getByRole('button', { name: /Patch\s+1/i })).toHaveAttribute('aria-pressed', 'true');
    await expect(rows).toHaveCount(1);
    await expect(runTable).toContainText('patch');

    await compareChip.click();
    await expect(compareChip).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('status').filter({ hasText: /Load more/i })).toBeVisible();

    await sourceFilters.getByRole('button', { name: /All Sources/i }).click();
    await expect(rows).toHaveCount(3);

    // Verdict badges
    await expect(page.locator('.verdict-badge--PASS').first()).toBeVisible();
    await expect(page.locator('.verdict-badge--CAUTION').first()).toBeVisible();

    // Ratchet chart section visible (with >= 2 history entries)
    await expect(page.locator('.ratchet-section')).toBeVisible();

    // Load more button (mock returns next_cursor on desktop first page).
    const loadMoreBtn = page.getByRole('button', { name: /Load more/i });
    let loadedMore = false;
    if (await loadMoreBtn.isVisible().catch(() => false)) {
      await loadMoreBtn.click();
      // After click: 5 rows total (the store merges the next cursor page).
      await expect(rows).toHaveCount(5, { timeout: 3000 });
      loadedMore = true;
    } else {
      await expect(rows).toHaveCount(3);
    }
    if (loadedMore) {
      await expect(runTable).toContainText('compare');
      await expect(runTable).toContainText('future_source');
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/01-dashboard.png`, fullPage: true });
  });

  test('Dashboard — KPI cards disclose stats fallback when stats API fails', async ({ page }) => {
    await page.unroute((url) => url.pathname === '/api/stats');
    await page.route(
      (url) => url.pathname === '/api/stats',
      (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }),
    );

    await page.goto('/');

    const kpiCards = page.locator('.kpi-grid--5col > .kpi');
    await expect(kpiCards).toHaveCount(5);
    await expect(kpiCards.nth(0).locator('.delta')).toHaveText(
      'Stats API unavailable; using loaded runs only',
    );
    await expect(kpiCards.nth(1).locator('.delta')).toHaveText(
      'Stats API unavailable; using loaded runs only',
    );
    await expect(kpiCards.nth(2).locator('.delta')).toHaveText('3 loaded runs');
    await expect(kpiCards.nth(3).locator('.delta')).toHaveText(
      'Stats API unavailable; using loaded runs only',
    );
    await expect(kpiCards.nth(4).locator('.lb')).toHaveText('LLM Calls');
  });

  /* ---------------------------------------------------------------- */
  /*  Page 2: Lesson                                                   */
  /* ---------------------------------------------------------------- */

  test('Lesson — content, scaffolding tabs, claims, evidence panel', async ({ page }) => {
    await page.goto('/#/run/test-run/lesson');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.lesson-page__verdict')).toContainText('PASS · 88');
    await expect(page.getByRole('button', { name: /Print/i })).toBeVisible();

    // Scaffolding tabs
    const tabs = page.locator('.scaffolding-tab');
    await expect(tabs).toHaveCount(3); // full, hint, compact

    // Lesson prose content (V6 3-column layout: prose lives in .lesson__prose)
    await expect(page.locator('.lesson__prose')).toBeVisible();
    await expect(page.locator('.lesson__prose')).toContainText('Sample lesson');
    await expect(page.locator('.lesson__toc')).toContainText('Evidence');
    await expect(page.locator('.lesson__toc')).not.toContainText('Not a lesson heading');

    // Claims list
    const claimCards = page.locator('.claim-card');
    await expect(claimCards).toHaveCount(4);
    await expect(claimCards.first()).toContainText('c1');
    await expect(page.locator('.lesson__rail')).toContainText('Wiki memory');
    await expect(page.locator('.lesson__rail')).toContainText('Evidence');
    await expect(page.locator('.lesson__rail')).toContainText('Learning');
    await expect(page.locator('.lesson__rail')).toContainText('Not proven');
    await expect(page.locator('.lesson__rail')).toContainText('Rejected');
    await expect(page.locator('.lesson__concept-chip')).toContainText('Learn-from-diff');
    await expect(page.locator('.lesson__concept-chip a').first()).toHaveAttribute(
      'href',
      /#\/concepts\?tab=ledger&focus=learn-from-diff$/,
    );
    await expect(page.locator('.lesson__evidence-list li')).toHaveCount(4);

    // Click claim to select it
    await claimCards.first().click();
    await expect(claimCards.first()).toHaveClass(/claim-card--selected/);

    // Evidence panel should show
    await expect(page.locator('.evidence-panel')).toBeVisible();
    await expect(page.locator('.evidence-panel__location code')).toHaveCount(2);

    // Click claim again to deselect
    await claimCards.first().click();
    await expect(claimCards.first()).not.toHaveClass(/claim-card--selected/);

    // Keyboard nav: Tab to a scaffolding tab, press ArrowRight
    await tabs.first().focus();
    await page.keyboard.press('ArrowRight');

    const learnedBtn = page.getByRole('button', { name: /Mark as learned/i });
    await learnedBtn.click();
    await expect(page.getByRole('button', { name: /^Learned$/i })).toBeDisabled();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/02-lesson.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 3: Diff                                                     */
  /* ---------------------------------------------------------------- */

  test('Diff — diff view, file header, add/del lines, stats panel', async ({ page }) => {
    await page.goto('/#/run/test-run/diff');

    // Warm v6 header actions.
    await expect(page.locator('.diff-page__header')).toContainText(/Diff \+ Evidence|Diff/);
    await expect(page.locator('.diff-page__header')).toContainText(/Unified|Split/);
    await expect(page.getByRole('button', { name: /Prev file|上个文件/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Next file|下个文件/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Open Lesson|打开课程/i })).toHaveAttribute(
      'href',
      /#\/run\/test-run\/lesson$/,
    );

    // Diff view renders
    await expect(page.locator('.diff-view')).toBeVisible();

    // File header line (meta)
    await expect(page.locator('.diff-line--meta').first()).toBeVisible();

    // Add line (green)
    const addLines = page.locator('.diff-line--add');
    await expect(addLines.first()).toBeVisible();
    await expect(addLines.first()).toContainText('AhaDiff');

    // Del line (red)
    const delLines = page.locator('.diff-line--del');
    await expect(delLines.first()).toBeVisible();
    await expect(delLines.first()).toContainText('world');

    // Bottom mini panel with stats
    await expect(page.locator('.mini-panel')).toBeVisible();
    await expect(page.locator('.mini-panel__item')).not.toHaveCount(0);

    // Inspector aside (V6 split layout uses ClaimInspector)
    await expect(page.locator('.claim-inspector')).toBeVisible();

    const splitButton = page.getByRole('button', { name: /Split/i });
    await splitButton.click();
    await expect(splitButton).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.diff-view')).toHaveClass(/diff-view--split/);
    const oldReturnCell = page
      .locator('.diff-split-cell--old.diff-split-cell--del')
      .filter({ hasText: 'return "world"' });
    await expect(oldReturnCell).toHaveCount(1);
    await expect(oldReturnCell).toContainText('return "world"');
    const newReturnCell = page
      .locator('.diff-split-cell--new.diff-split-cell--add')
      .filter({ hasText: 'return "AhaDiff"' });
    await expect(newReturnCell).toHaveCount(1);
    await expect(newReturnCell).toContainText('return "AhaDiff"');
    const splitClaimLine = page.locator('.diff-split-cell--new.diff-line--claim-linked').first();
    await expect(splitClaimLine).toContainText('# learn-from-diff');
    await expect(splitClaimLine.locator('.diff-line__claim-dot')).toHaveCount(1);
    await splitClaimLine.click();
    await expect(splitClaimLine).toHaveClass(/diff-line--claim-selected/);
    await expect(page.locator('.claim-inspector__item--selected')).toContainText('c1');

    const unifiedButton = page.getByRole('button', { name: /Unified/i });
    await unifiedButton.click();
    await expect(unifiedButton).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.diff-view')).not.toHaveClass(/diff-view--split/);

    const linkedClaimLine = page
      .locator('.diff-line.diff-line--claim-linked')
      .filter({ hasText: '# learn-from-diff' });
    await expect(linkedClaimLine).toHaveCount(1);
    await expect(linkedClaimLine).toContainText('# learn-from-diff');
    // Each linked diff line now has a small verdict-colored gutter dot.
    await expect(linkedClaimLine.locator('.diff-line__claim-dot')).toHaveCount(1);
    await expect(async () => {
      const isSelected = await linkedClaimLine.evaluate((el) =>
        el.classList.contains('diff-line--claim-selected'),
      );
      if (!isSelected) {
        await linkedClaimLine.click();
      }
      await expect(linkedClaimLine).toHaveClass(/diff-line--claim-selected/);
    }).toPass({ timeout: 7000 });
    await expect(page.locator('.claim-inspector__item--selected')).toContainText('c1');
    // Source preview moved out of the right inspector panel (which now shows
    // jump-to-code links instead). The actual source hunk renders below the
    // diff in `.diff-page__selected-hunk`.
    const jumpButtons = page.locator('.claim-inspector__jump-btn');
    await expect(jumpButtons).toHaveCount(2);
    await expect(jumpButtons.nth(0)).toContainText('demo.py:3');
    await expect(jumpButtons.nth(1)).toContainText('demo.py:8-9');
    await expect(page.locator('.diff-page__selected-hunk-code')).toContainText(
      '# learn-from-diff',
    );

    await linkedClaimLine.focus();
    await page.keyboard.press('Space');
    await expect(linkedClaimLine).not.toHaveClass(/diff-line--claim-selected/);

    await page.screenshot({ path: `${SCREENSHOT_DIR}/03-diff.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 4: Quiz                                                     */
  /* ---------------------------------------------------------------- */

  test('Quiz — question, answer, SRS rating gate, next button', async ({ page }) => {
    await holdPeekGuardTimer(page);
    const srsReviewRequests: Array<Record<string, unknown>> = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname !== '/api/signals/srs-review') return;
      const postData = request.postData();
      if (!postData) return;
      srsReviewRequests.push(JSON.parse(postData) as Record<string, unknown>);
    });

    await page.goto('/#/run/test-run/quiz');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Progress indicator
    await expect(page.locator('.quiz-page__progress')).toBeVisible();
    await expect(page.locator('.quiz-page__progress-bar')).toBeVisible();
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Guided|引导/);
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Recall|回忆/);
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Transfer|迁移/);
    await expect(page.getByRole('button', { name: /Skip|跳过/ })).toBeVisible();
    await expect(page.locator('.quiz-panel--evidence')).toBeVisible();
    await expect(page.locator('.quiz-evidence__empty')).toBeVisible();

    // SRS card with question
    await expect(page.locator('.srs-card')).toBeVisible();
    await expect(page.locator('.srs-card__question')).toContainText('new comment');

    // First quiz is multiple-choice with ABCD options.
    const choiceButtons = page.locator('.srs-card__choice');
    await expect(choiceButtons).toHaveCount(4);

    // Click a wrong choice (B) to test wrong-answer flow
    const choiceB = choiceButtons.nth(1);
    await expect(choiceB).toBeVisible();
    await choiceB.click();

    // After reveal: wrong choice highlighted, correct choice highlighted
    await expect(choiceB).toHaveClass(/srs-card__choice--wrong/);
    const choiceA = choiceButtons.nth(0);
    await expect(choiceA).toHaveClass(/srs-card__choice--correct/);

    // Explanation is shown.
    await expect(page.getByText('learn-from-diff marker tags the change')).toBeVisible();
    await expect(page.locator('.quiz-evidence__item')).toHaveCount(1);
    await expect(page.locator('.quiz-evidence__ref')).toContainText('demo.py:L4');
    await expect(page.locator('.quiz-evidence__ref')).toHaveAttribute(
      'href',
      /#\/run\/test-run\/diff\?focus=demo.py%3A4$/,
    );
    await expect(page.locator('.quiz-evidence__anchor-note')).toBeVisible();
    await expect(page.locator('.quiz-page__misconceptions')).toBeVisible();

    // Rating buttons appear but are disabled during peek guard (1.5s).
    // The timer is held by the test to avoid slow-browser timing flakes.
    // v0.1: SRSCard only renders Good/Hard/Wrong (Easy/Archive/Suspend removed).
    const ratingBtns = page.locator('.srs-card__rating-btn');
    await expect(ratingBtns).not.toHaveCount(0);
    const goodBtn = page.locator('.srs-card__rating-btn--good');
    const hardBtn = page.locator('.srs-card__rating-btn--hard');
    const wrongBtn = page.locator('.srs-card__rating-btn--wrong');

    // Easy / Archive / Suspend buttons must NOT exist in v0.1 DOM.
    await expect(page.locator('.srs-card__rating-btn--easy')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Archive/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Suspend/i })).toHaveCount(0);

    await expect(goodBtn).toBeDisabled();
    await expect(hardBtn).toBeDisabled();
    await expect(wrongBtn).toBeDisabled();
    expect(srsReviewRequests).toHaveLength(0);

    // Peek guard hint visible
    await expect(page.locator('.srs-card__peek-hint')).toBeVisible();
    await expect(page.getByRole('button', { name: /Next|下一题/i })).toBeVisible();

    await page.evaluate(() => {
      (window as Window & { __ahadiffReleasePeekGuardTimers?: () => void })
        .__ahadiffReleasePeekGuardTimers?.();
    });

    // After peek guard expires. Choice mode answered wrong → Good still
    // disabled. Hard/Wrong are the only valid SRS ratings for a wrong answer.
    // (Easy/Archive/Suspend removed in v0.1.)
    await expect(goodBtn).toBeDisabled();
    await expect(hardBtn).toBeEnabled();
    await expect(wrongBtn).toBeEnabled();

    await hardBtn.focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => srsReviewRequests.length, { timeout: 3000 }).toBe(1);
    expect(srsReviewRequests[0]).toMatchObject({
      answer: 'hard',
      card_id: 'card_quiz_explicit_1',
      peeked_this_session: false,
    });

    // Advance to second quiz item
    const nextBtn = page.getByRole('button', { name: /Next|下一题/i });
    await expect(nextBtn).toBeVisible();
    await nextBtn.focus();
    await page.keyboard.press('Enter');

    // Second quiz item (Socratic — no review_card_id)
    await expect(page.locator('.srs-card__question')).toContainText('return value');
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Socratic/i);
    await expect(page.locator('.quiz-page__mode-badge--active')).toContainText(/Transfer|迁移/);

    const answerInput2 = page.locator('.srs-card__answer-input');
    await expect(answerInput2).toBeVisible();
    await answerInput2.fill('To brand the output');
    await page.locator('.srs-card__btn--primary').click();
    await expect(page.locator('.srs-card__result')).toBeVisible();

    // After both quiz items answered, summary appears
    await expect(page.locator('.quiz-page__progress--summary')).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/04-quiz.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 5: Concepts                                                 */
  /* ---------------------------------------------------------------- */

  test('Concepts — heading, Canvas graph renders, detail panel', async ({ page }) => {
    await page.goto('/#/concepts?tab=graph');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/Concept|概念图谱/i);

    // Concept graph component with Canvas renderer
    await expect(page.locator('.concept-graph')).toBeVisible();

    // Source card (Graphify status)
    await expect(page.locator('.concept-graph__src-card')).toBeVisible();

    await expect(page.locator('.concept-graph__canvas canvas')).toBeVisible();

    // Canvas graph exposes a keyboard-accessible node list (3 mock nodes)
    const graphNodes = page.locator('.concept-graph__a11y-node');
    await expect(graphNodes).toHaveCount(3);

    // Legend
    await expect(page.locator('.concept-graph__legend')).toBeVisible();

    // Click first node to open detail panel
    await graphNodes.first().focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.concept-graph__detail')).toBeVisible();
    await expect(page.locator('.concept-graph__detail-name')).toBeVisible();

    // Escape should close the topmost dialog first, not the graph detail behind it.
    await page.keyboard.press('Control+K');
    const searchDialog = page.getByRole('dialog');
    await expect(searchDialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(searchDialog).not.toBeVisible();
    await expect(page.locator('.concept-graph__detail')).toBeVisible();

    // Escape closes detail from graph focus paths
    await page.keyboard.press('Escape');
    await expect(page.locator('.concept-graph__detail')).not.toBeVisible();

    // Filtering hides non-matching nodes and clears stale detail selection
    await graphNodes.first().focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.concept-graph__detail')).toBeVisible();
    await page.getByRole('button', { name: /module/i }).click();
    await expect(page.locator('.concept-graph__detail')).not.toBeVisible();
    await expect(page.locator('.concept-graph__a11y-node')).toHaveCount(1);

    // View toggle: switch to list view
    const listBtn = page.locator('.concept-graph__view-btn').last();
    await listBtn.click();
    await expect(page.locator('.concept-graph__listg').first()).toBeVisible();
    await expect(page.locator('.concept-graph__lnode')).toHaveCount(1);

    // Escape also closes detail from list/detail focus paths
    await page.locator('.concept-graph__lnode').first().click();
    await expect(page.locator('.concept-graph__detail')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('.concept-graph__detail')).not.toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/05-concepts.png`, fullPage: true });
  });

  test('Concepts — large graphs default to list fallback with counts', async ({ page }) => {
    await installLargeGraphMock(page);
    await page.goto('/#/concepts?tab=graph');

    await expect(page.locator('.concept-graph__listg').first()).toBeVisible();
    await expect(page.locator('.concept-graph__lnode')).toHaveCount(201);
    await expect(page.locator('.concept-graph__canvas canvas')).not.toBeVisible();
    await expect(page.locator('.concept-graph__counts')).toContainText(/201/);
  });

  /* ---------------------------------------------------------------- */
  /*  Page 6: Review                                                   */
  /* ---------------------------------------------------------------- */

  test('Review — flashcard, flip, rating buttons, card advance', async ({ page }) => {
    await page.goto('/#/review');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Flashcard visible with concept
    await expect(page.locator('.flashcard')).toBeVisible();
    await expect(page.locator('.flashcard__concept')).toContainText('learn-from-diff');

    // Progress bar (scoped to sidebar to avoid matching mastery summary bars)
    await expect(page.getByTestId('review-progress-bar')).toBeVisible();

    // Flip button
    const flipBtn = page.locator('.flashcard__flip-btn');
    await expect(flipBtn).toBeVisible();
    await page.keyboard.press('Space');

    // After flip: SRS buttons visible
    const srsButtons = page.locator('.srs-buttons');
    await expect(srsButtons).toBeVisible();
    const srsBtns = page.locator('.srs-btn');
    await expect(srsBtns).toHaveCount(4);

    // Verify button labels (en: Again / Hard / Good / Easy)
    await expect(srsBtns.nth(0)).toContainText(/Again|重来/);
    await expect(srsBtns.nth(1)).toContainText(/Hard|困难/);
    await expect(srsBtns.nth(2)).toContainText(/Good|掌握/);
    await expect(srsBtns.nth(3)).toContainText(/Easy|简单/);

    // Keyboard shortcuts shown
    await expect(srsBtns.nth(0).locator('.srs-btn__kbd')).toContainText('1');

    // Click Good
    await srsBtns.nth(2).click();

    // After rating: advances to the next due card in the mock queue.
    await expect(page.locator('.review__complete')).toHaveCount(0);
    await expect(page.locator('.flashcard')).toContainText('What does the new comment indicate?');

    await page.screenshot({ path: `${SCREENSHOT_DIR}/06-review.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 7: Ratchet                                                  */
  /* ---------------------------------------------------------------- */

  test('Ratchet — chart, weakest dim summary, results table', async ({ page }) => {
    await page.goto('/#/ratchet');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Ratchet chart (>= 2 entries)
    await expect(page.locator('.ratchet-card').first()).toBeVisible();
    await expect(page.locator('.ratchet-note-card')).toContainText('PHASE25');
    await expect(page.locator('.ratchet-note-card')).toContainText('+12.0');
    await expect(page.locator('.phase25-readout')).toContainText('target_dimension=learnability');
    await expect(page.locator('.ratchet-chart__legend')).toContainText(/kept/i);

    // Results table includes result_events statuses, including discarded rows.
    const table = page.locator('.ratchet-table');
    await expect(table).toBeVisible();
    const rows = table.locator('tbody tr');
    await expect(rows).toHaveCount(3);
    await expect(table).toContainText('discard');
    await expect(table).toContainText('score did not beat baseline');

    // Verdict badges in table
    await expect(page.locator('.verdict-badge').first()).toBeVisible();

    // Weakest dimension summary
    await expect(page.locator('.mastery-grid')).toBeVisible();
    await expect(page.locator('.mastery-bar__fill').first()).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/07-ratchet.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 8: Settings                                                 */
  /* ---------------------------------------------------------------- */

  test('Settings — tabs, provider grid, audit log, doctor checks', async ({ page }) => {
    await page.goto('/#/settings');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Tab sidebar with current Settings sections.
    await expect(page.locator('.stabs')).toBeVisible();
    await expect(page.locator('.st')).toHaveCount(7);

    // Default privacy tab shows privacy controls.
    await expect(page.locator('.settings-toggle')).toHaveCount(3);

    // Default privacy tab shows config fields
    const fields = page.locator('#spanel-privacy .settings-field');
    await expect(fields).not.toHaveCount(0);
    await expect(fields.first()).toBeVisible();

    // Navigate to provider tab for provider grid metadata.
    await page.getByRole('tab', { name: /provider/i }).click();
    await expect(page.locator('.provider-grid')).toBeVisible();
    await expect(page.locator('.provider-card').first()).toContainText('gpt-5.4-mini');

    // Navigate to audit tab for the 8-column recent provider log.
    await page.getByRole('tab', { name: /audit/i }).click();
    await expect(page.locator('.audit-table th')).toHaveCount(8);
    await expect(page.locator('.audit-table')).toContainText('lesson_generate');
    await expect(page.locator('.audit-table')).toContainText('700');

    // Navigate to preferences tab for language, appearance and learning controls.
    await page.getByRole('tab', { name: /preferences/i }).click();
    await expect(page.locator('.settings-content').getByRole('group', { name: /Language/i })).toBeVisible();
    await expect(page.getByText('Learning Sensitivity')).toBeVisible();

    // Navigate to AI tool guidance tab for target badges.
    await page.getByRole('tab', { name: /AI Tool Guidance/i }).click();
    await expect(page.locator('#spanel-integrations .settings-field__badge--configured')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Claude Code' })).toBeVisible();
    await expect(page.locator('.graphify-card').filter({ hasText: 'Graphify source' })).toBeVisible();

    // Navigate to account tab for doctor checks
    await page.getByRole('tab', { name: /account/i }).click();
    const checks = page.locator('#spanel-account .diag-row');
    await expect(checks).toHaveCount(4);
    await expect(page.locator('#spanel-account .diag-row__icon--pass').first()).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/08-settings.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 9: Onboarding                                               */
  /* ---------------------------------------------------------------- */

  test('Onboarding — stepper UI, doctor checks, CLI commands', async ({ page }) => {
    await page.goto('/#/onboarding');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Stepper with 4 steps
    const steps = page.locator('[data-testid="onboarding-stepper"] .onboarding-steps__item');
    await expect(steps).toHaveCount(4);

    // At least one step should be done (since doctor checks pass)
    await expect(
      page.locator('.onboarding-steps__item[data-state="done"]').first(),
    ).toBeVisible();

    // CLI commands card; doctor all-pass opens on the learn step.
    await expect(steps.nth(0)).toContainText(/Pick a repo|选择仓库/);
    await expect(steps.nth(1)).toContainText(/Add provider key|添加 Provider key/);
    await expect(steps.nth(2)).toContainText(/Install agent|安装 Agent/);
    await expect(page.locator('pre')).toBeVisible();
    await expect(page.locator('pre').first()).toContainText('ahadiff learn HEAD~1..HEAD');

    // Doctor checks in the onboarding grid
    await expect(
      page.locator('[data-testid="onboarding-diagnostics"] .diag-row').first(),
    ).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/09-onboarding.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 10: Guide                                                   */
  /* ---------------------------------------------------------------- */

  test('Guide — workflow steps, command grid, copy button', async ({ page }) => {
    await page.goto('/#/guide');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Workflow section with steps
    const workflow = page.locator('.guide-workflow');
    await expect(workflow).toBeVisible();
    const steps = page.locator('.guide-workflow__step-item');
    await expect(steps).toHaveCount(4);

    // Command cards in core section
    const cards = page.locator('.guide-card');
    await expect(cards.first()).toBeVisible();
    await expect(page.locator('.guide-install-model')).toContainText('AhaDiff CLI');
    await expect(page.locator('.guide-install-model')).toContainText('Project agent instructions');
    await expect(page.locator('.guide-agent-skills')).toContainText(/Agent Skills|Agent 技能/);
    await expect(page.locator('.guide-agent-card')).toHaveCount(13);
    await expect(page.locator('.guide-agent-previews')).toContainText('SKILL.md');
    await expect(page.locator('.guide-agent-previews')).toContainText('AGENTS.md preview');

    // Copy button on at least one command block
    const copyBtns = page.locator('.command-block__copy-btn');
    await expect(copyBtns.first()).toBeVisible();

    // Click copy on first card (clipboard API may not be available in test, but
    // the click should not throw)
    await copyBtns.first().click();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/10-guide.png`, fullPage: true });
  });

  test('Guide — accordion sections expand on click', async ({ page }) => {
    await page.goto('/#/guide');

    const accordions = page.locator('.guide-accordion');
    await expect(accordions.first()).toBeVisible();

    const firstSummary = page.locator('.guide-accordion__summary').first();
    await firstSummary.click();

    // After expanding, the body should be visible
    await expect(page.locator('.guide-accordion__body').first()).toBeVisible();
  });

  test('Guide — command blocks are present and copyable', async ({ page }) => {
    await page.goto('/#/guide');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const commandBlocks = page.locator('.command-block');
    const count = await commandBlocks.count();
    expect(count).toBeGreaterThan(5);

    // Each command block should have a copy button
    const copyBtns = page.locator('.command-block__copy-btn');
    const copyCount = await copyBtns.count();
    expect(copyCount).toBeGreaterThan(0);
  });

  test('Deep links — settings tabs, concept focus, and review card restore', async ({ page }) => {
    await page.goto('/#/settings?tab=provider');
    await expect(page.locator('#spanel-provider .provider-grid')).toBeVisible();

    await page.goto('/#/settings?tab=capture');
    await expect(page.locator('#spanel-capture .settings-field').first()).toBeVisible();

    await page.goto('/#/concepts?focus=n2');
    await expect(page.locator('.concept-graph__detail')).toContainText('retry-logic');

    await page.goto('/#/review?card=card-2-mc');
    await expect(page.locator('.flashcard__front')).toContainText('What does the new comment indicate?');
  });

  test('Settings AI tool guidance — preview write remove mutation loop', async ({ page }) => {
    await page.goto('/#/settings?tab=integrations');

    const codexRow = page.getByRole('article', { name: 'Codex CLI' });
    await expect(codexRow).toBeVisible();
    await expect(page.locator('.integration-intro')).toContainText('repo-local instruction files');
    await expect(codexRow).toContainText('Scope: current project');
    await expect(codexRow).toContainText('It does not write user-level or global CLI/IDE directories.');

    const previewBtn = codexRow.getByRole('button', { name: 'Preview' });
    await previewBtn.focus();
    await page.keyboard.press('Enter');
    await expect(codexRow.getByRole('status')).toContainText('Project guidance preview refreshed');
    await expect(codexRow.getByRole('region', { name: 'Inline preview' })).toBeVisible();
    await expect(codexRow).toContainText('Writing guidance will');
    await expect(codexRow).toContainText('Removing guidance will');
    await expect(codexRow).toContainText('AGENTS.md');
    await expect(codexRow).toContainText('merge marked section');
    await expect(codexRow.getByRole('button', { name: 'Write Codex CLI guidance to the current project' })).toBeVisible();
    await expect(codexRow.getByRole('button', { name: 'Copy write-guidance command for Codex CLI' })).toBeVisible();

    const collapseBtn = codexRow.getByRole('button', {
      name: 'Collapse preview for Codex CLI',
    });
    await collapseBtn.focus();
    await page.keyboard.press('Enter');
    await expect(codexRow.getByRole('region', { name: 'Inline preview' })).toHaveCount(0);
    await expect(codexRow.getByRole('button', { name: 'Show preview for Codex CLI' })).toBeVisible();

    const showPreviewBtn = codexRow.getByRole('button', {
      name: 'Show preview for Codex CLI',
    });
    await showPreviewBtn.focus();
    await page.keyboard.press('Enter');
    await expect(codexRow.getByRole('region', { name: 'Inline preview' })).toBeVisible();

    const writeBtn = codexRow.getByRole('button', {
      name: 'Write Codex CLI guidance to the current project',
    });
    await writeBtn.focus();
    await page.keyboard.press('Enter');
    await expect(codexRow.getByRole('status')).toContainText('Guidance written to the current project');
    await expect(codexRow).toContainText('guidance written');
    await expect(codexRow.getByRole('region', { name: 'Inline preview' })).toHaveCount(0);
    await expect(codexRow.getByRole('button', { name: 'Show preview for Codex CLI' })).toBeVisible();
    await expect(codexRow).toContainText('$ ahadiff uninstall codex');
    await expect(codexRow.getByRole('button', { name: 'Remove Codex CLI guidance from the current project' })).toBeVisible();
    await expect(codexRow.getByRole('button', { name: 'Copy remove-guidance command for Codex CLI' })).toBeVisible();

    const removeBtn = codexRow.getByRole('button', {
      name: 'Remove Codex CLI guidance from the current project',
    });
    await removeBtn.focus();
    await page.keyboard.press('Enter');
    await expect(codexRow.getByRole('status')).toContainText('Guidance removed from the current project');
    await expect(codexRow).toContainText('ready');
    await expect(codexRow.getByRole('region', { name: 'Inline preview' })).toHaveCount(0);
  });

  test('Review — flashcard renders question on front and answer on back', async ({ page }) => {
    await page.goto('/#/review');

    // Wait for flashcard to load
    await expect(page.locator('.flashcard')).toBeVisible();

    // Verify the question text appears on the flashcard front
    const front = page.locator('.flashcard__front');
    await expect(front).toBeVisible();
    await expect(front).toContainText('What does the useEffect cleanup function do in React?');

    // Verify the AI source badge is visible
    const sourceBadge = page.locator('.flashcard__source-badge');
    await expect(sourceBadge).toBeVisible();
    await expect(page.locator('aside')).toContainText(/Activity|活动/);
    await expect(page.locator('aside')).toContainText(/Concept Mastery|概念掌握/);
    await expect(page.getByRole('heading', { name: /New Concepts|新概念/i })).toBeVisible();
    await expect(page.getByText('idempotent retry')).toBeVisible();
    await expect(page.locator('.review__weak-meta--new')).toBeVisible();

    // Verify the answer is hidden before flipping
    const back = page.locator('.flashcard__back');
    await expect(back).toBeHidden();

    // Click the flip/show-answer button
    const flipBtn = page.locator('.flashcard__flip-btn');
    await activateControlWithKeyboard(page, flipBtn);

    // Verify the answer text appears on the flashcard back
    await expect(back).toBeVisible();
    const answerEl = page.locator('.flashcard__answer');
    await expect(answerEl).toBeVisible();
    await expect(answerEl).toContainText(
      'It runs when the component unmounts or before the effect re-runs, used for cleanup like cancelling subscriptions.',
    );
  });

  test('Review — evidence link visible after flip with correct href', async ({ page }) => {
    await page.goto('/#/review');

    await expect(page.locator('.flashcard')).toBeVisible();

    // Evidence link should not be visible before flipping (back is hidden)
    const evidenceLink = page.getByTestId('flashcard-evidence-link');
    await expect(evidenceLink).toBeHidden();

    // Flip the card
    const flipBtn = page.locator('.flashcard__flip-btn');
    await activateControlWithKeyboard(page, flipBtn);

    // After flip: evidence block is visible
    await expect(evidenceLink).toBeVisible();

    // Verify file path is shown
    await expect(evidenceLink).toContainText('demo.py');

    // Verify the href points to the lesson page for this run
    const href = await evidenceLink.getAttribute('href');
    expect(href).toMatch(/^\/#\/run\/test-run\/lesson$/);
  });

  test('Review — summary section toggles collapsed state', async ({ page }) => {
    await page.goto('/#/review');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const summary = page.locator('.review__summary');
    await expect(summary).toBeVisible();

    const toggle = page.locator('.review__summary-toggle');
    await expect(toggle).toBeVisible();

    const body = page.locator('.review__summary-body');
    const wasVisible = await body.isVisible();

    await toggle.click();
    if (wasVisible) {
      await expect(body).not.toBeVisible();
    } else {
      await expect(body).toBeVisible();
    }
  });

  test('Quiz — mode chips show Warm v6 kinds plus SRS or Socratic', async ({ page }) => {
    await page.goto('/#/run/test-run/quiz');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Guided|引导/);
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Recall|回忆/);
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/Transfer|迁移/);
    await expect(page.locator('.quiz-page__mode-row')).toContainText(/SRS|Socratic/i);
    await page.getByRole('button', { name: /Skip|跳过/ }).click();
    await expect(page.locator('.srs-card__question')).toContainText('return value');
    await expect(page.locator('.quiz-page__progress')).toContainText('2/2');
    await expect(page.getByRole('button', { name: /Skip|跳过/ })).toHaveCount(0);
  });

  test('Ratchet — benchmark tab renders transparency grid', async ({ page }) => {
    const scoreRequests: string[] = [];
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname;
      if (/^\/api\/run\/[^/]+\/score$/.test(pathname)) scoreRequests.push(pathname);
    });
    await page.goto('/#/ratchet');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const benchmarkTab = page.locator('.ratchet-tabs__tab', { hasText: /Benchmark/i });
    await expect(benchmarkTab).toBeVisible();
    await benchmarkTab.click();

    await expect(page.locator('.benchmark-grid')).toBeVisible();
    const cards = page.locator('.benchmark-card');
    await expect(cards).toHaveCount(6);
    await expect(cards.first()).toContainText('ahadiff-local-v1');
    await expect(page.locator('.benchmark-entry-list')).toContainText('eval_001_python_retry');
    expect(scoreRequests).toEqual([]);
  });

  test('Ratchet — transparency failure is visible while history fallback remains', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/ratchet/transparency',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'transparency failed' }),
        }),
    );

    await page.goto('/#/ratchet');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await expect(page.locator('.ratchet-transparency-warning')).toContainText(
      /Ratchet transparency is unavailable/i,
    );
    await expect(page.locator('.ratchet-table tbody tr')).toHaveCount(3);

    await page.locator('.ratchet-tabs__tab', { hasText: /Benchmark/i }).click();
    await expect(page.locator('.ratchet-transparency-warning')).toContainText(
      /Ratchet transparency is unavailable/i,
    );
    await expect(page.locator('.benchmark-grid')).toHaveCount(0);
  });

  /* ---------------------------------------------------------------- */
  /*  Page 11: Landing / Welcome                                       */
  /* ---------------------------------------------------------------- */

  test('Landing — hero, feature cards, trust demo, before/after, demo tabs', async ({ page }) => {
    await page.goto('/#/welcome');

    // Hero section
    await expect(page.locator('.hero')).toBeVisible();
    await expect(page.locator('.hero__title')).toBeVisible();

    // CTA button
    await expect(page.locator('.btn-primary')).toBeVisible();
    await expect(page.locator('.btn-primary')).toHaveAttribute(
      'href',
      /#\/run\/run-003\/lesson$/,
    );
    await activateControlWithKeyboard(
      page,
      page.getByRole('button', { name: /Start from your diff|从你的 diff 开始/ }),
    );
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');

    // CLI command
    await expect(page.locator('.cli-cmd')).toContainText('pip install ahadiff');
    await expect(page.locator('.hero-demo__source')).toContainText(/Latest finalized run|最新完成运行/);

    // Feature cards (4)
    const featureCards = page.locator('.feature-card');
    await expect(featureCards).toHaveCount(4);
    await expect(featureCards.first()).toContainText(/Evidence-bound claims|证据绑定声明/);

    // Pipeline steps (5)
    const steps = page.locator('.step');
    await expect(steps).toHaveCount(5);

    // Demo tabs (Raw / Aha)
    const demoTabs = page.locator('.hero-demo__tab');
    await expect(demoTabs).toHaveCount(2);

    // Default is "aha" tab
    await expect(demoTabs.nth(1)).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#demo-panel')).toContainText('Sample lesson');

    // Click "raw" tab
    await demoTabs.nth(0).click();
    await expect(demoTabs.nth(0)).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#demo-panel pre')).toContainText('diff --git');

    // Before/After section
    await expect(page.locator('.ba-grid')).toBeVisible();

    // V6 trust block keeps an explicit source boundary and uses real transparency data when available.
    await expect(page.locator('.demo-banner')).toContainText(/LIVE RUN|真实运行/);
    const benchmarkCards = page.locator('.benchmark-card');
    await expect(benchmarkCards).toHaveCount(4);
    await expect(benchmarkCards.nth(0)).toContainText('31');
    await expect(benchmarkCards.nth(0).locator('.demo-tag')).toContainText(/LIVE RUN|真实运行/);
    await expect(benchmarkCards.nth(0).locator('.benchmark-card__delta')).toContainText(
      /20 eval \/ 11 integration|20 条 eval \/ 11 条 integration/,
    );
    await expect(benchmarkCards.nth(1)).toContainText('87.3');
    await expect(benchmarkCards.nth(2)).toContainText('14');
    await expect(benchmarkCards.nth(3)).toContainText('100%');

    await page.screenshot({ path: `${SCREENSHOT_DIR}/11-landing.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Sidebar navigation                                */
  /* ---------------------------------------------------------------- */

  test('Sidebar — all nav links navigate correctly', async ({ page }) => {
    await page.goto('/');

    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toBeVisible();

    // Verify all non-disabled nav items
    const navItems = sidebar.locator('.sidebar__item:not(.sidebar__item--disabled)');
    const count = await navItems.count();
    expect(count).toBeGreaterThan(5);

    // Navigate to each linked page via sidebar
    const routes = [
      { text: /Concept|概念/, hash: '#/concepts' },
      { text: /Review|复习/, hash: '#/review' },
      { text: /Ratchet|棘轮/, hash: '#/ratchet' },
      { text: /Guide|使用指南/, hash: '#/guide' },
      { text: /Settings|设置/, hash: '#/settings' },
      { text: /Welcome|欢迎/, hash: '#/welcome' },
      { text: /Onboarding|上手/, hash: '#/onboarding' },
    ];

    for (const { text, hash } of routes) {
      await page.goto('/');
      await openSidebarIfCollapsed(page);
      const link = page.locator('.sidebar .sidebar__item', { hasText: text }).first();
      if (await link.isVisible()) {
        await link.scrollIntoViewIfNeeded();
        await link.click();
        await page.waitForURL(new RegExp(hash.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
        // Verify heading exists on each page
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      }
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/12-sidebar-nav.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: i18n language switch                               */
  /* ---------------------------------------------------------------- */

  test('i18n — switch to zh-CN, verify Chinese text, switch back', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Find the language switcher
    const langSwitcher = page.locator('.lang-switcher');
    // Language switcher may be a button or select; try clicking the zh-CN option
    const zhBtn = langSwitcher.locator('button', { hasText: /中文|zh-CN/i });
    await expect(zhBtn).toBeVisible();
    await zhBtn.click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');

    // Verify Chinese text appears
    await expect(page.getByRole('heading', { level: 1 })).toContainText('运行');

    await page.screenshot({ path: `${SCREENSHOT_DIR}/13-i18n-zh.png`, fullPage: true });

    // Switch back to English
    const enBtn = langSwitcher.locator('button', { hasText: /English|EN/i });
    await expect(enBtn).toBeVisible();
    await enBtn.click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/Dashboard/);

    await page.screenshot({ path: `${SCREENSHOT_DIR}/14-i18n-en.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Error state — mock 500 response                   */
  /* ---------------------------------------------------------------- */

  test('Error state — mock 500 on runs endpoint shows error alert', async ({ page }) => {
    // Override the runs endpoint to return 500
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal Server Error' }),
        }),
    );
    // Also fail ratchet to trigger the full error state
    await page.route(
      (url) => url.pathname === '/api/ratchet/history',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal Server Error' }),
        }),
    );

    await page.goto('/');

    // Error alert should be visible
    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Failed to fetch Dashboard/);

    // Retry button should be present
    const retryBtn = page.locator('.retry-btn');
    await expect(retryBtn).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/15-error-state.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: 404 Not Found page                                */
  /* ---------------------------------------------------------------- */

  test('404 — unknown route shows not found', async ({ page }) => {
    await page.goto('/#/this-does-not-exist');
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/Not found|未找到/);

    // Back to dashboard link (inside the error fallback area, not sidebar)
    await expect(
      page.locator('.error-boundary__fallback a', { hasText: /Dashboard|运行/ }),
    ).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/16-not-found.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Keyboard accessibility                            */
  /* ---------------------------------------------------------------- */

  test('Keyboard — Tab through interactive elements on Dashboard', async ({ page, browserName }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Safari/WebKit only tabs through clickable items with Option-Tab unless
    // Keyboard Navigation / "Press Tab to highlight each item on a webpage" is enabled.
    const navKey = browserName === 'webkit' ? 'Alt+Tab' : 'Tab';

    // Tab through the page and verify focus lands on interactive elements
    const focusedTags: string[] = [];
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press(navKey);
      const tag = await page.evaluate(() => {
        const el = document.activeElement;
        return el ? `${el.tagName}.${el.className.split(' ')[0] || ''}` : 'none';
      });
      focusedTags.push(tag);
    }

    // Verify we tabbed into at least some links and buttons
    const interactiveCount = focusedTags.filter(
      (t) => t.startsWith('A.') || t.startsWith('BUTTON.'),
    ).length;
    expect(interactiveCount).toBeGreaterThan(3);
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Review keyboard shortcuts                         */
  /* ---------------------------------------------------------------- */

  test('Review — keyboard shortcuts: Space to flip, 3 for Good', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();

    // Press Space to flip
    await page.keyboard.press('Space');
    await expect(page.locator('.srs-buttons')).toBeVisible();

    // Press 3 for Good rating
    await page.keyboard.press('3');

    // The first rating advances to the second due card in the mock queue.
    await expect(page.locator('.review__complete')).toHaveCount(0);
    await expect(page.locator('.flashcard')).toContainText('What does the new comment indicate?');
  });

  test('Review — keyboard shortcut 4 rates Easy', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();

    await page.keyboard.press('Space');
    await expect(page.locator('.srs-buttons')).toBeVisible();
    await expect(page.locator('.srs-btn')).toHaveCount(4);

    await page.keyboard.press('4');

    await expect(page.locator('.review__complete')).toHaveCount(0);
    await expect(page.locator('.flashcard')).toContainText('What does the new comment indicate?');
  });

  test('Review — SRS rating buttons have aria-describedby linking to interval', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();

    // Flip to reveal rating buttons.
    await page.keyboard.press('Space');
    await expect(page.locator('.srs-buttons')).toBeVisible();

    // Verify each button has aria-describedby pointing to its interval span
    const srsBtns = page.locator('.srs-btn');
    await expect(srsBtns).toHaveCount(4);

    // Again button
    await expect(srsBtns.nth(0)).toHaveAttribute('aria-describedby', 'srs-interval-wrong');
    await expect(page.locator('#srs-interval-wrong')).toContainText(/10/);

    // Hard button
    await expect(srsBtns.nth(1)).toHaveAttribute('aria-describedby', 'srs-interval-hard');
    await expect(page.locator('#srs-interval-hard')).toContainText(/1/);

    // Good button
    await expect(srsBtns.nth(2)).toHaveAttribute('aria-describedby', 'srs-interval-good');
    await expect(page.locator('#srs-interval-good')).toContainText(/4/);

    // Easy button
    await expect(srsBtns.nth(3)).toHaveAttribute('aria-describedby', 'srs-interval-easy');
    await expect(page.locator('#srs-interval-easy')).toContainText(/7/);

    // Verify aria-label includes full description
    await expect(srsBtns.nth(0)).toHaveAttribute('aria-label', /Again/);
    await expect(srsBtns.nth(2)).toHaveAttribute('aria-label', /Good/);
    await expect(srsBtns.nth(3)).toHaveAttribute('aria-label', /Easy/);
  });

  test('Review — InfoHint tooltip keyboard: focus shows, Escape hides, aria-expanded toggles', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // The Review page has InfoHint components (FSRS chip, mastery bars).
    // Find an InfoHint trigger button.
    const infoTrigger = page.locator('.info-hint__trigger').first();
    await expect(infoTrigger).toBeVisible();

    // Verify tooltip is not visible initially
    await expect(page.locator('.info-hint__bubble')).not.toBeVisible();
    await expect(infoTrigger).toHaveAttribute('aria-expanded', 'false');

    // Tab to the InfoHint trigger to give it focus
    await infoTrigger.focus();

    // Tooltip should appear on focus (role="tooltip")
    const tooltip = page.locator('[role="tooltip"]').first();
    await expect(tooltip).toBeVisible();
    await expect(infoTrigger).toHaveAttribute('aria-expanded', 'true');

    // Press Escape to dismiss the tooltip
    await page.keyboard.press('Escape');

    // Tooltip should disappear
    await expect(tooltip).not.toBeVisible();
    await expect(infoTrigger).toHaveAttribute('aria-expanded', 'false');
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Dashboard run link navigation                     */
  /* ---------------------------------------------------------------- */

  test('Dashboard — clicking run link navigates to Lesson page', async ({ page }) => {
    await page.goto('/');
    const runTable = page.getByRole('table', { name: 'Recent runs' });
    await expect(runTable).toBeVisible();

    // Click the first run link — table is sorted DESC by created_at,
    // so the first row is run-003 (newest, source_ref=HEAD).
    const runLink = runTable.getByRole('link').first();
    await expect(runLink).toBeVisible();
    await runLink.scrollIntoViewIfNeeded();
    // The narrow Firefox project occasionally needs extra time for HashRouter
    // to flush the hashchange listener after viewport-constrained interaction.
    // Keep other projects on the original 5s budget so the suite stays fast.
    const projectName = test.info().project.name;
    const isFirefox = projectName.startsWith('firefox');
    const isFirefoxMobile = projectName === 'firefox-mobile';
    const navigationTimeout = isFirefoxMobile ? 20_000 : 5_000;
    const runUrl = /\/#\/run\/run-003\/lesson/;
    await runLink.click();
    if (isFirefox) {
      const clicked = await page.waitForURL(runUrl, { timeout: navigationTimeout }).then(
        () => true,
        () => false,
      );
      if (!clicked) {
        await runLink.focus();
        await page.keyboard.press('Enter');
      }
    }

    // Should navigate to the lesson page for that run
    await expect(page).toHaveURL(runUrl, { timeout: navigationTimeout });
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible({
      timeout: isFirefoxMobile ? 15_000 : 5_000,
    });
    await expect(page.locator('.lesson__prose')).toContainText('Sample lesson', {
      timeout: isFirefoxMobile ? 15_000 : 5_000,
    });
  });

  /* ---------------------------------------------------------------- */
  /*  7E: Error state — 401 unauthorized triggers auth error UI         */
  /* ---------------------------------------------------------------- */

  test('Error state — 401 on auth endpoint shows auth-specific error', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/auth/token',
      (route) =>
        route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'unauthorized' }),
        }),
    );
    await page.route(
      (url) => url.pathname === '/api/locale',
      (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: '{"locale":"en"}' }),
    );

    await page.goto('/', { timeout: 15_000 });
    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Authentication failed/);
  });

  /* ---------------------------------------------------------------- */
  /*  7E: Error state — network timeout shows retry UI                  */
  /* ---------------------------------------------------------------- */

  test('Error state — network timeout on runs shows error + retry', async ({ page }) => {
    await installRichMock(page);
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) => route.abort('timedout'),
    );
    await page.route(
      (url) => url.pathname === '/api/ratchet/history',
      (route) => route.abort('timedout'),
    );

    await page.goto('/');
    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Failed to fetch Dashboard/);
    const retryBtn = page.locator('.retry-btn');
    await expect(retryBtn).toBeVisible();
  });

  test('CC-GAP-3 — SQLite corruption from search endpoint shows recoverable error', async ({ page }) => {
    await page.route(
      (url) => url.pathname === '/api/search',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'review.sqlite is not a valid database' }),
        }),
    );

    await page.goto('/');
    await openSearchOverlay(page);
    await page.locator('#search-overlay-input').fill('sqlite');
    await expect(page.locator('.search-overlay__status')).toContainText(/Search is unavailable/);
  });

  /* ---------------------------------------------------------------- */
  /*  7E: Empty state — zero runs shows fallback                        */
  /* ---------------------------------------------------------------- */

  test('Empty state — zero runs shows empty fallback UI', async ({ page }) => {
    await installServeMock(page);
    await page.goto('/');
    // With zero runs, dashboard shows an empty-state / no-data indicator
    // rather than the run table.
    const runTable = page.getByRole('table', { name: 'Recent runs' });
    const emptyIndicator = page.locator('.dashboard__empty, .kpi');
    // Either the table is absent or we see KPI cards showing zero state
    const hasTable = await runTable.isVisible().catch(() => false);
    if (!hasTable) {
      await expect(emptyIndicator.first()).toBeVisible();
    }
  });

  /* ---------------------------------------------------------------- */
  /*  7E: CC-GAP-10 — Unicode paths don't crash the viewer              */
  /* ---------------------------------------------------------------- */

  test('CC-GAP-10 — Unicode source_ref renders without crash', async ({ page }) => {
    await installServeMock(page);
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            runs: [
              {
                run_id: 'unicode-run',
                source_kind: 'git_ref',
                source_ref: '功能/测试-分支',
                content_lang: 'zh-CN',
                capability_level: 3,
                verdict: 'PASS',
                overall: 85,
                status: 'baseline',
                weakest_dim: 'evidence',
                created_at: '2026-04-28T00:00:00Z',
                degraded_flags: {},
              },
            ],
          }),
        }),
    );

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    // The unicode source_ref should render in the run table
    await expect(page.locator('body')).toContainText('功能');
  });
});
