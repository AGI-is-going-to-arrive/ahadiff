import { expect, test } from '@playwright/test';
import { installServeMock } from '../fixtures/serve-mock';

test.describe('Provider Scope Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('should default to repo scope and toggle hint texts correctly', async ({ page }) => {
    // Navigate to Settings page and switch to Providers tab
    await page.goto('/#/settings');
    await page.getByRole('tab', { name: /provider/i }).click();

    // Click "Add Provider" button
    await page.getByRole('button', { name: 'Add Provider' }).click();

    // Scope radiogroup is visible
    const scopeLabel = page.getByText('Scope', { exact: true });
    await expect(scopeLabel).toBeVisible();

    // Check that "This repo" radio is checked by default
    const repoRadio = page.locator('input[value="repo"]');
    await expect(repoRadio).toBeChecked();

    const globalRadio = page.locator('input[value="global"]');
    await expect(globalRadio).not.toBeChecked();

    // Verify key hint defaults to repo variant
    const keyHint = page.locator('#provider-apikey-hint-new');
    await expect(keyHint).toContainText('.ahadiff/.env');
    await expect(keyHint).not.toContainText('0600');

    // Switch to global scope
    await page.getByText('All repos (global)', { exact: true }).click();
    await expect(globalRadio).toBeChecked();
    await expect(repoRadio).not.toBeChecked();

    // Key hint should change to global variant
    await expect(keyHint).toContainText('0600');
    await expect(keyHint).toContainText('%APPDATA%');
    await expect(keyHint).not.toContainText('.ahadiff/.env');

    // Switch back to repo scope
    await page.getByText('This repo', { exact: true }).click();
    await expect(repoRadio).toBeChecked();
    await expect(globalRadio).not.toBeChecked();

    // Key hint should restore to repo variant
    await expect(keyHint).toContainText('.ahadiff/.env');
    await expect(keyHint).not.toContainText('0600');
  });

  test('should render Global badge for a scope:global provider', async ({ page }) => {
    // Unroute the original /api/providers mock and register our custom mock
    await page.unroute((url) => url.pathname === '/api/providers');
    await page.route(
      (url) => url.pathname === '/api/providers',
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            providers: [
              {
                alias: 'global-openai',
                role: 'generate',
                provider_class: 'openai',
                provider_kind: 'openai',
                model_name: 'gpt-4o',
                base_url: 'https://api.openai.com/v1',
                api_key_env: 'OPENAI_API_KEY',
                key_status: 'configured',
                api_family: 'openai_chat',
                api_family_version: 'v1',
                probed: true,
                probed_max_context: 128000,
                scope: 'global',
              },
            ],
          }),
        });
      },
    );

    await page.goto('/#/settings');
    await page.getByRole('tab', { name: /provider/i }).click();

    const providerCard = page.locator('.provider-card').filter({ hasText: 'global-openai' });
    await expect(providerCard).toBeVisible();

    // The card is collapsed by default, click header to expand
    await providerCard.locator('.provider-card__header').click();

    // Verify "From global config" badge is visible
    const badge = providerCard.locator('.provider-card__scope-info');
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('From global config');
    await expect(badge).toContainText('This repository can override specific fields locally.');
  });
});
