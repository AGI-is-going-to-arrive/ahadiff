/**
 * walkthrough.spec.ts — Comprehensive functional walkthrough of every AhaDiff
 * viewer page and interaction. Uses the same mock API pattern as serve-mock.ts,
 * but provides richer data to exercise more code paths (multi-run dashboard,
 * ratchet history with 3+ entries, etc.).
 */
import { expect, test, type Page } from '@playwright/test';
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
  // V6 collapses the sidebar into a drawer up to 1024px (matches AhaDiff
  // Warm v6.html:361 @media max-width:1024px). Use the same boundary so the
  // helper opens the drawer on tablet (768px) viewports as well.
  const isMobile = await page.evaluate(
    () => window.matchMedia('(max-width: 1024px)').matches,
  );
  if (!isMobile) return;
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
                source_kind: 'git_ref',
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
                source_kind: 'git_ref',
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
                source_kind: 'git_ref',
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
            { run_id: 'run-003', source_ref: 'HEAD', eval_bundle_version: 'bundle-v2', overall: 88, verdict: 'PASS', status: 'baseline', weakest_dim: 'evidence', timestamp: '2026-04-27T08:00:00Z' },
          ],
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
            '{"claim_id":"c1","verdict":"verified","source_hunks":[{"file":"demo.py","start":3,"end":3,"side":"new"},{"file":"demo.py","start":8,"end":9,"side":"new"}],"statement":"adds learn-from-diff comment and follow-up evidence"}',
          content_lang: 'en',
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

    // KPI cards visible (3-col grid for >= 2 runs)
    const kpiCards = page.locator('.kpi-card');
    await expect(kpiCards).toHaveCount(3);

    // Run list table
    const runTable = page.locator('table.run-list');
    await expect(runTable).toBeVisible();
    const rows = runTable.locator('tbody tr');
    await expect(rows).toHaveCount(3);

    // Verdict badges
    await expect(page.locator('.verdict-badge--PASS').first()).toBeVisible();
    await expect(page.locator('.verdict-badge--CAUTION').first()).toBeVisible();

    // Ratchet chart section visible (with >= 2 history entries)
    await expect(page.locator('.ratchet-section')).toBeVisible();

    // Load more button (mock returns next_cursor on first page)
    const loadMoreBtn = page.locator('.load-more-btn');
    await expect(loadMoreBtn).toBeVisible();
    await loadMoreBtn.click();
    // After click: 4 rows total (the store merges runs de-duped by run_id)
    await expect(rows).toHaveCount(4, { timeout: 3000 });

    await page.screenshot({ path: `${SCREENSHOT_DIR}/01-dashboard.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 2: Lesson                                                   */
  /* ---------------------------------------------------------------- */

  test('Lesson — content, scaffolding tabs, claims, evidence panel', async ({ page }) => {
    await page.goto('/#/run/test-run/lesson');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Scaffolding tabs
    const tabs = page.locator('.scaffolding-tab');
    await expect(tabs).toHaveCount(3); // full, medium, minimal

    // Lesson prose content (V6 3-column layout: prose lives in .lesson__prose)
    await expect(page.locator('.lesson__prose')).toBeVisible();
    await expect(page.locator('.lesson__prose')).toContainText('Sample lesson');
    await expect(page.locator('.lesson__toc')).toContainText('Evidence');
    await expect(page.locator('.lesson__toc')).not.toContainText('Not a lesson heading');

    // Claims list
    const claimCards = page.locator('.claim-card');
    await expect(claimCards).toHaveCount(1);
    await expect(claimCards.first()).toContainText('c1');

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

    await page.screenshot({ path: `${SCREENSHOT_DIR}/02-lesson.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 3: Diff                                                     */
  /* ---------------------------------------------------------------- */

  test('Diff — diff view, file header, add/del lines, stats panel', async ({ page }) => {
    await page.goto('/#/run/test-run/diff');

    // Heading
    await expect(page.getByRole('heading', { name: /diff|差异/i, level: 1 })).toBeVisible();

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

    const linkedClaimLine = page.locator('.diff-line--claim-linked').first();
    await expect(linkedClaimLine).toContainText('# learn-from-diff');
    await linkedClaimLine.click();
    await expect(linkedClaimLine).toHaveClass(/diff-line--claim-selected/);
    await expect(page.locator('.claim-inspector__item--selected')).toContainText('c1');
    await expect(page.locator('.claim-inspector__source-group')).toHaveCount(2);
    const sourceCodes = page.locator('.claim-inspector__source-code');
    await expect(sourceCodes.nth(0)).toContainText('# learn-from-diff');
    await expect(sourceCodes.nth(1)).toContainText('lesson-ready');
    await expect(sourceCodes.nth(1)).toContainText('evidence-ready');

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

    // SRS card with question
    await expect(page.locator('.srs-card')).toBeVisible();
    await expect(page.locator('.srs-card__question')).toContainText('new comment');

    // Real quiz.jsonl is open-answer, not legacy choices/answer_index.
    const answerInput = page.locator('.srs-card__answer-input');
    await expect(answerInput).toBeVisible();
    await answerInput.fill('A learn-from-diff marker');

    // "Show Answer" button should now be enabled; click it
    const showAnswerBtn = page.locator('.srs-card__btn--primary');
    await expect(showAnswerBtn).toBeEnabled();
    await showAnswerBtn.click();

    // After reveal: result indicator appears
    await expect(page.locator('.srs-card__result')).toBeVisible();

    // Expected answer and explanation are shown.
    await expect(page.getByText('Expected answer')).toBeVisible();
    await expect(page.getByText('learn-from-diff marker tags the change')).toBeVisible();
    await expect(page.locator('.quiz-page__misconceptions')).toBeVisible();

    // Rating buttons appear but are disabled during peek guard (1.5s).
    // The timer is held by the test to avoid slow-browser timing flakes.
    const ratingBtns = page.locator('.srs-card__rating-btn');
    await expect(ratingBtns).not.toHaveCount(0);
    const archiveBtn = page.getByRole('button', { name: /Archive/i });
    const suspendBtn = page.getByRole('button', { name: /Suspend/i });
    const easyBtn = page.locator('.srs-card__rating-btn--easy');
    const goodBtn = page.locator('.srs-card__rating-btn--good');
    const hardBtn = page.locator('.srs-card__rating-btn--hard');
    const wrongBtn = page.locator('.srs-card__rating-btn--wrong');

    await expect(easyBtn).toBeDisabled();
    await expect(goodBtn).toBeDisabled();
    await expect(hardBtn).toBeDisabled();
    await expect(wrongBtn).toBeDisabled();
    await expect(archiveBtn).toBeDisabled();
    await expect(suspendBtn).toBeDisabled();
    expect(srsReviewRequests).toHaveLength(0);

    // Peek guard hint visible
    await expect(page.locator('.srs-card__peek-hint')).toBeVisible();

    await page.evaluate(() => {
      (window as Window & { __ahadiffReleasePeekGuardTimers?: () => void })
        .__ahadiffReleasePeekGuardTimers?.();
    });

    // After peek guard expires. Because the quiz revealed
    // the answer, the backend treats this review as peeked and still rejects
    // Easy/Good. The UI must only allow Hard/Wrong SRS submissions here.
    await expect(easyBtn).toBeDisabled();
    await expect(goodBtn).toBeDisabled();
    await expect(hardBtn).toBeEnabled();
    await expect(wrongBtn).toBeEnabled();
    await expect(archiveBtn).toBeEnabled();
    await expect(suspendBtn).toBeEnabled();

    await hardBtn.click();
    await expect.poll(() => srsReviewRequests.length, { timeout: 3000 }).toBe(1);
    expect(srsReviewRequests[0]).toMatchObject({
      answer: 'hard',
      card_id: 'card_quiz_explicit_1',
      peeked_this_session: true,
    });

    // Since there is only 1 quiz item, the summary should appear
    await expect(page.locator('.quiz-page__progress--summary')).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/04-quiz.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 5: Concepts                                                 */
  /* ---------------------------------------------------------------- */

  test('Concepts — heading, concept graph renders (full mode SVG)', async ({ page }) => {
    await page.goto('/#/concepts');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/Concept|概���/i);

    // Concept graph component
    await expect(page.locator('.concept-graph')).toBeVisible();

    // Full mode badge (mock concept has related_claims → full mode)
    await expect(page.locator('.concept-graph__mode-badge')).toBeVisible();

    // SVG graph with at least one node group
    const svgNodes = page.locator('.concept-graph__node');
    await expect(svgNodes).not.toHaveCount(0);

    // Click node to activate tooltip
    await svgNodes.first().click();
    await expect(page.locator('.concept-graph__tooltip--visible')).toBeVisible();
    await expect(page.locator('.concept-graph__tooltip-name')).toContainText('Learn-from-diff');

    // Press Escape to dismiss
    await page.keyboard.press('Escape');

    await page.screenshot({ path: `${SCREENSHOT_DIR}/05-concepts.png`, fullPage: true });
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

    // Progress bar
    await expect(page.locator('.mastery-bar')).toBeVisible();

    // Flip button
    const flipBtn = page.locator('.flashcard__flip-btn');
    await expect(flipBtn).toBeVisible();
    await flipBtn.click();

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

    // After rating: session complete (only 1 card)
    await expect(page.locator('.review__complete')).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/06-review.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 7: Ratchet                                                  */
  /* ---------------------------------------------------------------- */

  test('Ratchet — chart, weakest dim summary, history table', async ({ page }) => {
    await page.goto('/#/ratchet');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Ratchet chart (>= 2 entries)
    await expect(page.locator('.ratchet-card').first()).toBeVisible();

    // History table
    const table = page.locator('.ratchet-table');
    await expect(table).toBeVisible();
    const rows = table.locator('tbody tr');
    await expect(rows).toHaveCount(3);

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

  test('Settings — config fields, doctor checks', async ({ page }) => {
    await page.goto('/#/settings');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Config fields
    const fields = page.locator('.settings-field');
    await expect(fields).not.toHaveCount(0);
    // Verify specific fields rendered
    await expect(fields.first()).toBeVisible();

    // API key status badge
    await expect(page.locator('.settings-field__badge--configured')).toBeVisible();

    // Doctor checks
    const checks = page.locator('.doctor-check');
    await expect(checks).toHaveCount(4);
    // All pass
    await expect(page.locator('.doctor-check__icon--pass').first()).toBeVisible();

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
    const steps = page.locator('.stepper__step');
    await expect(steps).toHaveCount(4);

    // At least one step should be done (since doctor checks pass)
    await expect(page.locator('.stepper__step--done').first()).toBeVisible();

    // CLI commands card
    await expect(page.locator('pre')).toBeVisible();
    await expect(page.locator('pre').first()).toContainText('pip install ahadiff');

    // Doctor checks in the onboarding grid
    await expect(page.locator('.doctor-check').first()).toBeVisible();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/09-onboarding.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 10: Skills                                                  */
  /* ---------------------------------------------------------------- */

  test('Skills — agent grid, install commands, copy button', async ({ page }) => {
    await page.goto('/#/skills');

    // Heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Agent cards
    const cards = page.locator('.agent-card');
    await expect(cards).toHaveCount(3); // claude, codex, cursor

    // Detected badge on claude
    await expect(page.locator('.agent-card__status--installed').first()).toBeVisible();

    // Copy button visible
    const copyBtns = page.locator('.copy-btn');
    await expect(copyBtns.first()).toBeVisible();

    // Click copy on first card (clipboard API may not be available in test, but
    // the click should not throw)
    await copyBtns.first().click();

    await page.screenshot({ path: `${SCREENSHOT_DIR}/10-skills.png`, fullPage: true });
  });

  /* ---------------------------------------------------------------- */
  /*  Page 11: Landing / Welcome                                       */
  /* ---------------------------------------------------------------- */

  test('Landing — hero, pipeline steps, before/after, demo tabs', async ({ page }) => {
    await page.goto('/#/welcome');

    // Hero section
    await expect(page.locator('.hero')).toBeVisible();
    await expect(page.locator('.hero__title')).toBeVisible();

    // CTA button
    await expect(page.locator('.btn-primary')).toBeVisible();

    // CLI command
    await expect(page.locator('.cli-cmd')).toContainText('pip install ahadiff');

    // Pipeline steps (5)
    const steps = page.locator('.step');
    await expect(steps).toHaveCount(5);

    // Demo tabs (Raw / Aha)
    const demoTabs = page.locator('.hero-demo__tab');
    await expect(demoTabs).toHaveCount(2);

    // Default is "aha" tab
    await expect(demoTabs.nth(1)).toHaveAttribute('aria-selected', 'true');

    // Click "raw" tab
    await demoTabs.nth(0).click();
    await expect(demoTabs.nth(0)).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#demo-panel pre')).toContainText('diff --git');

    // Before/After section
    await expect(page.locator('.ba-grid')).toBeVisible();

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
      { text: /Skills|技能/, hash: '#/skills' },
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
    if (await zhBtn.isVisible()) {
      await zhBtn.click();
      // After locale switch, page should reload or re-render
      await page.waitForTimeout(500);

      // Verify Chinese text appears
      await expect(page.getByRole('heading', { level: 1 })).toContainText('运行');

      await page.screenshot({ path: `${SCREENSHOT_DIR}/13-i18n-zh.png`, fullPage: true });

      // Switch back to English
      const enBtn = langSwitcher.locator('button', { hasText: /English|EN/i });
      if (await enBtn.isVisible()) {
        await enBtn.click();
        await page.waitForTimeout(500);
        await expect(page.getByRole('heading', { level: 1 })).toContainText(/Dashboard/);
      }
    }

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
    // NotFoundPage renders h2 (inside AppShell which has no h1)
    const heading = page.getByRole('heading', { level: 2 });
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

    // Session complete
    await expect(page.locator('.review__complete')).toBeVisible();
  });

  test('Review — keyboard shortcuts: 4 for Easy', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();

    await page.keyboard.press('Space');
    await expect(page.locator('.srs-buttons')).toBeVisible();

    await page.keyboard.press('4');

    await expect(page.locator('.review__complete')).toBeVisible();
  });

  /* ---------------------------------------------------------------- */
  /*  Cross-cutting: Dashboard run link navigation                     */
  /* ---------------------------------------------------------------- */

  test('Dashboard — clicking run link navigates to Lesson page', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('table.run-list')).toBeVisible();

    // Click the first run link — table is sorted DESC by created_at,
    // so the first row is run-003 (newest, source_ref=HEAD).
    const runLink = page.locator('.run-list__link').first();
    await expect(runLink).toBeVisible();
    await runLink.click();

    // Should navigate to the lesson page for that run
    await expect(page).toHaveURL(/\/#\/run\/run-003\/lesson/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});
