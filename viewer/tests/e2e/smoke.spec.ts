import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('smoke', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('root renders and contains AhaDiff or Dashboard heading', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/AhaDiff/i);
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
  });

  test('mobile 375px viewport has no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('hash router diff route renders DiffViewer heading', async ({ page }) => {
    await page.goto('/#/run/test-run/diff');
    await expect(page.getByRole('heading', { name: /diff/i, level: 1 })).toBeVisible();
  });

  test('hash router lesson route renders Lesson heading', async ({ page }) => {
    await page.goto('/#/run/test-run/lesson');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router quiz route renders Quiz heading', async ({ page }) => {
    await page.goto('/#/run/test-run/quiz');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router concepts route renders Concepts heading', async ({ page }) => {
    await page.goto('/#/concepts');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router review route renders Review heading', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('review page shows flashcard with mock card data', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard')).toBeVisible();
    await expect(page.locator('.flashcard__concept')).toContainText('learn-from-diff');
  });

  test('review page flip reveals answer and rating buttons', async ({ page }) => {
    await page.goto('/#/review');
    await expect(page.locator('.flashcard__flip-btn')).toBeVisible();
    await page.locator('.flashcard__flip-btn').click();
    await expect(page.locator('.srs-buttons')).toBeVisible();
    const buttons = page.locator('.srs-btn');
    await expect(buttons).toHaveCount(3);
  });

  test('hash router ratchet route renders Ratchet heading', async ({ page }) => {
    await page.goto('/#/ratchet');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('hash router welcome/landing route renders hero', async ({ page }) => {
    await page.goto('/#/welcome');
    await expect(page.locator('.hero')).toBeVisible();
    await expect(page.locator('.hero__title')).toBeVisible();
  });

  test('landing page pipeline steps are visible', async ({ page }) => {
    await page.goto('/#/welcome');
    const steps = page.locator('.step');
    await expect(steps).toHaveCount(5);
  });

  test('hash router settings route renders Settings heading', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('settings page shows config fields and doctor checks', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.locator('.settings-field')).not.toHaveCount(0);
    await expect(page.locator('.doctor-check')).not.toHaveCount(0);
  });

  test('hash router onboarding route renders stepper', async ({ page }) => {
    await page.goto('/#/onboarding');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.stepper__step')).toHaveCount(4);
  });

  test('hash router skills route renders agent grid', async ({ page }) => {
    await page.goto('/#/skills');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.agent-card')).not.toHaveCount(0);
  });

  test('skills page shows copy button for supported targets', async ({ page }) => {
    await page.goto('/#/skills');
    await expect(page.locator('.copy-btn').first()).toBeVisible();
  });
});
