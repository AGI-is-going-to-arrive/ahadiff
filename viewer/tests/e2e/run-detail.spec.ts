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
});
