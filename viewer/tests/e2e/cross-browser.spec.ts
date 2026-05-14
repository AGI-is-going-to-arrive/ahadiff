import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('cross-browser corner cases', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await installServeMock(page);
  });

  test('rapid locale toggle settles to final state', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const switcher = page.getByRole('group', { name: /Language|语言/i });
    const zhBtn = switcher.getByRole('button', { name: '简体中文' });
    const enBtn = switcher.getByRole('button', { name: 'English' });

    // Rapid toggle: en -> zh-CN -> en -> zh-CN without awaiting intermediate UI
    await zhBtn.click();
    await enBtn.click();
    await zhBtn.click();
    await enBtn.click();

    // Final state should be en
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);
    await expect(enBtn).toHaveAttribute('aria-pressed', 'true');

    expect(errors).toHaveLength(0);
  });

  test('rapid sequential navigation produces no JS errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Navigate rapidly: Dashboard -> Lesson -> Quiz -> Concepts
    await page.goto('/#/run/test-run/lesson');
    await page.goto('/#/run/test-run/quiz');
    await page.goto('/#/concepts');

    // Final page should render Concepts heading
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Concept/i);

    expect(errors).toHaveLength(0);
  });

  test('dashboard fetch error shows alert then recovers on retry navigation', async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Override /api/runs to fail
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'error' }),
    );

    await page.goto('/');

    // Should show error alert
    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible();

    // Remove the failing route and re-add the success route
    await page.unroute((url) => url.pathname === '/api/runs');
    await page.route(
      (url) => url.pathname === '/api/runs',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ runs: [] }),
        }),
    );

    // Navigate away and back to trigger refetch
    await page.goto('/#/concepts');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);

    // Error alert should be gone, empty state should show
    await expect(page.locator('.dashboard__empty')).toBeVisible();

    expect(errors).toHaveLength(0);
  });

  test('empty runs list renders Dashboard empty hint', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Default mock returns { runs: [] }
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Dashboard/i);
    // Verify empty state hint text is visible
    const emptyHint = page.locator('.dashboard__empty-hint');
    await expect(emptyHint).toBeVisible();
    await expect(emptyHint).toHaveText(/ahadiff learn/);

    expect(errors).toHaveLength(0);
  });

  test('Dashboard empty Learn dialog suppresses global search shortcut', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Start your first Learn Run/i }).click();

    const learnDialog = page.getByRole('dialog', { name: /Start a Learn Run/i });
    await expect(learnDialog).toBeVisible();
    await learnDialog.getByRole('button', { name: /More options/i }).focus();

    await page.keyboard.press('Control+K');

    await expect(page.getByRole('dialog')).toHaveCount(1);
    await expect(learnDialog).toBeVisible();
    await expect(page.getByRole('dialog', { name: /Search|搜索/i })).toHaveCount(0);
  });

  test('topbar wires search button + active New-Run button', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const viewport = page.viewportSize();
    const isMobile = viewport != null && viewport.width < 768;
    const usesMobilePreview = viewport != null && viewport.width <= 768;

    const searchBtn = page.getByRole('button', { name: /Open search/i });
    const newRun = page.locator('.topbar__btn--primary');

    if (isMobile) {
      await expect(searchBtn).toHaveCount(0);
      await page.keyboard.press('Control+K');
    } else {
      await expect(searchBtn).toBeVisible();
      await expect(searchBtn).toHaveCount(1);
      await expect(searchBtn).not.toHaveAttribute('aria-disabled', 'true');
      await expect(newRun).toBeVisible();
      await expect(newRun).not.toBeDisabled();
      await searchBtn.click();
    }

    await expect(page.getByRole('dialog', { name: /Search|搜索/i })).toBeVisible();
    await expect(page.locator('.topbar')).toHaveAttribute('inert', '');
    await expect(page.locator('.app-shell__body')).toHaveAttribute('inert', '');
    await expect(page.locator('#search-overlay-input')).toBeFocused();
    const backgroundTookFocus = await page.evaluate(() => {
      const target = document.querySelector<HTMLElement>('.topbar__search, .topbar__mobile-btn');
      target?.focus();
      return !document.activeElement?.closest('.search-overlay');
    });
    expect(backgroundTookFocus).toBe(false);

    const allFilter = page.getByRole('radio', { name: /^All$/ });
    const conceptsFilter = page.getByRole('radio', { name: /^Concepts$/ });
    await expect(allFilter).toHaveAttribute('aria-checked', 'true');
    await allFilter.focus();
    await page.keyboard.press('ArrowRight');
    await expect(conceptsFilter).toBeFocused();
    await expect(conceptsFilter).toHaveAttribute('aria-checked', 'true');
    await page.keyboard.press('ArrowLeft');
    await expect(allFilter).toBeFocused();
    await expect(allFilter).toHaveAttribute('aria-checked', 'true');
    await page.keyboard.press('ArrowRight');
    await expect(conceptsFilter).toBeFocused();
    await expect(conceptsFilter).toHaveAttribute('aria-checked', 'true');

    const searchTablesSeen: string[] = [];
    await page.route(
      (url) => url.pathname === '/api/search',
      (route) => {
        searchTablesSeen.push(new URL(route.request().url()).searchParams.get('tables') ?? '');
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            results: [
              {
                source_table: 'result_events',
                primary_key: 'event-123',
                snippet: 'task timeout result',
                rank: 0.9,
                href: '#/run/run-real/lesson',
              },
            ],
          }),
        });
      },
    );
    const searchInput = page.locator('#search-overlay-input');
    await searchInput.focus();
    await searchInput.fill('timeout');
    await expect(searchInput).toHaveValue('timeout');
    const resultButton = page.locator('.search-overlay__result-btn').first();
    await expect(resultButton).toContainText('task timeout result');
    expect(searchTablesSeen.at(-1)).toBe('concepts');
    await resultButton.click();
    if (usesMobilePreview) {
      await page.locator('.search-overlay__preview-btn').click();
    }
    await expect(page).toHaveURL(/#\/run\/run-real\/lesson/);
  });

  test('ScaffoldingTabs keyboard navigation moves focus correctly', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const tablist = page.getByRole('tablist', { name: /Lesson/i });
    await expect(tablist).toBeVisible();

    // Tab order: compact → hint → full (simple-to-complex)
    // Mock weak concepts return scaffolding_level='full', so auto-recommendation selects Full
    const compactTab = tablist.getByRole('tab', { name: /Compact/i });
    const hintTab = tablist.getByRole('tab', { name: /Hint/i });
    const fullTab = tablist.getByRole('tab', { name: /Full/i });

    await expect(fullTab).toHaveAttribute('aria-selected', 'true');

    // Focus the active tab then use ArrowLeft (full is rightmost, move left)
    await fullTab.focus();
    await page.keyboard.press('ArrowLeft');
    await expect(hintTab).toHaveAttribute('aria-selected', 'true');
    await expect(hintTab).toBeFocused();

    await page.keyboard.press('ArrowLeft');
    await expect(compactTab).toHaveAttribute('aria-selected', 'true');
    await expect(compactTab).toBeFocused();

    // ArrowRight should move back
    await page.keyboard.press('ArrowRight');
    await expect(hintTab).toHaveAttribute('aria-selected', 'true');
    await expect(hintTab).toBeFocused();

    expect(errors).toHaveLength(0);
  });

  test('long lesson content does not produce horizontal overflow', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    // Override lesson endpoint with very long content
    const longLine = 'A'.repeat(2000);
    const longContent = `# Very Long Lesson\n\n${longLine}\n\nEnd of lesson.`;
    await page.route(
      (url) => /^\/api\/run\/[^/]+\/lesson$/.test(url.pathname),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'test-run',
            artifact_type: 'lesson',
            content: longContent,
            content_lang: 'en',
          }),
        }),
    );

    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Wait for lesson content to render (V6 3-column: prose container)
    await expect(page.locator('.lesson__prose')).toBeVisible();

    // Check that document-level horizontal overflow does not exist
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    expect(errors).toHaveLength(0);
  });

  test('mobile viewport opens sidebar drawer from hamburger', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const menuButton = page.locator('.topbar__mobile-btn');
    const sidebar = page.locator('#sidebar');
    await expect(menuButton).toBeVisible();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).not.toHaveClass(/sidebar--open/);

    await menuButton.click();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    await expect(sidebar).toHaveClass(/sidebar--open/);

    const nav = page.getByRole('navigation', { name: /Navigation|导航/i });
    await expect(nav).toBeVisible();

    const dashboardLink = nav.getByRole('link', { name: /Dashboard/ });
    await expect(dashboardLink).toBeVisible();

    const conceptsLink = nav.getByRole('link', { name: /Concepts/ });
    await expect(conceptsLink).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).not.toHaveClass(/sidebar--open/);
    await expect(menuButton).toBeFocused();

    await menuButton.click();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    await expect(sidebar).toHaveClass(/sidebar--open/);

    await page.locator('.app-shell__backdrop').click();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).not.toHaveClass(/sidebar--open/);
    await expect(menuButton).toBeFocused();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    expect(errors).toHaveLength(0);
  });

  test('769-1024px viewport shows icon-only sidebar rail (no drawer)', async ({ page }) => {
    /* Three-state sidebar paradigm (matches AppShell.tsx + Sidebar.css):
     *   <=768px:    drawer overlay with hamburger (JS-driven, isMobileNav=true)
     *   769-1024px: icon-only rail (~56px, sidebar always visible, hamburger hidden)
     *   >1024px:    full sidebar (~248px, hamburger hidden, labels visible)
     */
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto('/');

    const menuButton = page.locator('.topbar__mobile-btn');
    const sidebar = page.locator('#sidebar');

    // -- Top boundary (1024px): still icon rail, hamburger hidden.
    await expect(menuButton).toBeHidden();
    await expect(sidebar).toBeVisible();
    await expect(sidebar).not.toHaveClass(/sidebar--open/);
    const sidebarBox = await sidebar.boundingBox();
    expect(sidebarBox?.width).toBeGreaterThanOrEqual(50);
    expect(sidebarBox?.width).toBeLessThanOrEqual(70);

    // -- Mid-rail (~900px): explicit assertion that the icon rail is the
    //    visible paradigm (not the drawer). Brand text + nav labels collapse,
    //    but icons remain visible and NavLinks keep aria-label semantics.
    await page.setViewportSize({ width: 900, height: 800 });
    await expect(menuButton).toBeHidden();
    await expect(sidebar).toBeVisible();
    await expect(sidebar.locator('.sidebar__brand-text')).toBeHidden();
    await expect(sidebar.locator('.sidebar__label-main').first()).toBeHidden();
    await expect(sidebar.locator('.sidebar__icon').first()).toBeVisible();
    const dashboardRailLink = sidebar.getByRole('link', { name: /Dashboard/ });
    await expect(dashboardRailLink).toBeVisible();
    await dashboardRailLink.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#\/?$/);
    const disabledLesson = sidebar.locator('.sidebar__item--disabled[aria-label^="Lesson"]').first();
    await expect(disabledLesson).toHaveAttribute('title', /Lesson.*run/i);
    const railOverflow = await sidebar.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(railOverflow).toBeLessThanOrEqual(0);

    // -- Bottom boundary (769px): still icon rail.
    await page.setViewportSize({ width: 769, height: 768 });
    await expect(menuButton).toBeHidden();
    await expect(sidebar).toBeVisible();

    // -- 768px crosses into drawer mode: hamburger appears, sidebar closed.
    await page.setViewportSize({ width: 768, height: 1024 });
    await expect(menuButton).toBeVisible();
    await expect(sidebar).not.toHaveClass(/sidebar--open/);
    await page.evaluate(() => {
      document.documentElement.setAttribute('dir', 'rtl');
    });
    await expect
      .poll(() => sidebar.evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).m41))
      .toBeGreaterThan(0);
    await menuButton.click();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    await expect
      .poll(() => sidebar.evaluate((el) => Math.round(new DOMMatrixReadOnly(getComputedStyle(el).transform).m41)))
      .toBe(0);
    await page.keyboard.press('Escape');
    await page.evaluate(() => {
      document.documentElement.removeAttribute('dir');
    });

    // -- Above 1024px: full sidebar returns with labels visible.
    await page.setViewportSize({ width: 1025, height: 800 });
    await expect(menuButton).toBeHidden();
    await expect(sidebar).toBeVisible();
    const justFullBox = await sidebar.boundingBox();
    expect(justFullBox?.width).toBeGreaterThan(200);

    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(menuButton).toBeHidden();
    await expect(sidebar).toBeVisible();
    const fullBox = await sidebar.boundingBox();
    expect(fullBox?.width).toBeGreaterThan(200);
    await expect(sidebar.locator('.sidebar__brand-text')).toBeVisible();
    await expect(sidebar.locator('.sidebar__label-main').first()).toBeVisible();
  });
});
