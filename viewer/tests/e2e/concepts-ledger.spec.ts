import { test, expect } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('Concepts Ledger tab', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('renders ledger tab as default with table', async ({ page }) => {
    await page.goto('/#/concepts');
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();

    const tabList = page.getByRole('tablist');
    await expect(tabList).toBeVisible();

    const ledgerTab = page.getByRole('tab', { name: /ledger|台账/i });
    await expect(ledgerTab).toHaveAttribute('aria-selected', 'true');

    const table = page.locator('.concept-ledger__table');
    await expect(table).toBeVisible();

    await expect(page.locator('.concept-ledger__name').first()).toContainText('Learn-from-diff');
  });

  test('switches between ledger and graph tabs', async ({ page }) => {
    await page.goto('/#/concepts');

    const graphTab = page.getByRole('tab', { name: /graph|图谱/i });
    await graphTab.click();
    await expect(graphTab).toHaveAttribute('aria-selected', 'true');

    const ledgerPanel = page.locator('#concepts-panel-ledger');
    await expect(ledgerPanel).toBeHidden();

    const graphPanel = page.locator('#concepts-panel-graph');
    await expect(graphPanel).toBeVisible();
  });

  test('tab keyboard navigation wraps with ArrowRight/ArrowLeft', async ({ page }) => {
    await page.goto('/#/concepts');

    const ledgerTab = page.getByRole('tab', { name: /ledger|台账/i });
    await ledgerTab.focus();

    await page.keyboard.press('ArrowRight');
    const graphTab = page.getByRole('tab', { name: /graph|图谱/i });
    await expect(graphTab).toBeFocused();
    await expect(graphTab).toHaveAttribute('aria-selected', 'true');

    await page.keyboard.press('ArrowRight');
    await expect(ledgerTab).toBeFocused();
    await expect(ledgerTab).toHaveAttribute('aria-selected', 'true');
  });

  test('ledger shows concept entries with run chips', async ({ page }) => {
    await page.goto('/#/concepts');
    await expect(page.locator('.concept-ledger__table')).toBeVisible();

    const rows = page.locator('.concept-ledger__table tbody tr');
    await expect(rows).toHaveCount(2);

    const runChips = page.locator('.concept-ledger__chip--run');
    expect(await runChips.count()).toBeGreaterThanOrEqual(1);
  });

  test('ledger shows total count', async ({ page }) => {
    await page.goto('/#/concepts');
    const total = page.locator('.concept-ledger__total');
    await expect(total).toContainText('2 / 2');
  });

  test('concepts page respects tab query param', async ({ page }) => {
    await page.goto('/#/concepts?tab=graph');

    const graphTab = page.getByRole('tab', { name: /graph|图谱/i });
    await expect(graphTab).toHaveAttribute('aria-selected', 'true');
  });

  test('focus deep links open the graph tab', async ({ page }) => {
    await page.goto('/#/concepts?focus=n2');

    const graphTab = page.getByRole('tab', { name: /graph|图谱/i });
    await expect(graphTab).toHaveAttribute('aria-selected', 'true');
  });

  test('same-route tab query changes sync the selected tab', async ({ page }) => {
    await page.goto('/#/concepts?tab=graph');
    const graphTab = page.getByRole('tab', { name: /graph|图谱/i });
    await expect(graphTab).toHaveAttribute('aria-selected', 'true');

    await page.evaluate(() => {
      window.location.hash = '#/concepts?tab=ledger';
    });

    const ledgerTab = page.getByRole('tab', { name: /ledger|台账/i });
    await expect(ledgerTab).toHaveAttribute('aria-selected', 'true');
  });

  test('run chips update the hash run filter and empty filters clear safely', async ({ page }) => {
    await page.goto('/#/concepts?tab=ledger');
    await page.getByRole('button', { name: 'test-run-2' }).click();

    await expect(page).toHaveURL(/run=test-run-2/);
    await expect(page.locator('.concept-ledger__table tbody tr')).toHaveCount(1);

    await page.getByRole('button', { name: /clear/i }).click();
    await expect(page).not.toHaveURL(/run=/);
    await expect(page.locator('.concept-ledger__table tbody tr')).toHaveCount(2);
  });

  test('shows empty state when a run filter has no ledger entries', async ({ page }) => {
    await page.goto('/#/concepts?run=missing-run');

    await expect(page.locator('.concept-ledger__empty')).toBeVisible();
  });
});
