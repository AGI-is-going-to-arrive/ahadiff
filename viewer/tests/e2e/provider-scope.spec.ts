import { expect, test, type Locator, type Page } from '@playwright/test';
import type { ModelLimitsResponse, ThinkingLevel } from '../../src/api/types';
import { installServeMock } from '../fixtures/serve-mock';

function capabilityResponse(
  modelName: string,
  acceptedLevels: ThinkingLevel[],
  providerClass = 'openai',
): ModelLimitsResponse {
  return {
    alias: null,
    provider_class: providerClass,
    model_name: modelName,
    max_context_tokens: 256_000,
    max_input_tokens: 200_000,
    max_output_tokens: 56_000,
    max_context_known: true,
    max_input_known: true,
    max_output_known: true,
    context_policy: 'shared_pool',
    source: 'registry',
    confidence: 'high',
    warnings: [],
    thinking: {
      supported: acceptedLevels.length > 0,
      accepted_levels: acceptedLevels,
      payload_mode: 'reasoning_effort',
      warnings: [],
    },
  };
}

async function openProviderDraft(page: Page, modelName: string, providerClass = 'openai'): Promise<Locator> {
  await page.goto('/#/settings?tab=provider');
  await page.getByRole('button', { name: 'Add Provider' }).click();
  const form = page.getByTestId('provider-card-new');
  await form.locator('#provider-alias-input').fill('test-provider');
  await form.locator('#provider-class-new').selectOption(providerClass);
  await form.locator('#provider-baseurl-new').fill('https://api.example.test/v1');
  await form.locator('#provider-model-new').fill(modelName);
  return form;
}

async function captureProviderSaves(page: Page): Promise<Record<string, unknown>[]> {
  const payloads: Record<string, unknown>[] = [];
  await page.route((url) => url.pathname === '/api/providers', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const value: unknown = route.request().postDataJSON();
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error('Expected a provider save payload');
    }
    const payload = value as Record<string, unknown>;
    payloads.push(payload);
    await route.fulfill({
      json: {
        updated: true,
        provider: {
          ...payload,
          provider_kind: 'openai',
          key_status: 'configured',
          probed: false,
          probed_max_context: null,
          available_models: [],
        },
      },
    });
  });
  return payloads;
}

test.describe('Provider Scope Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('localizes role configuration errors and translates an existing error after a locale change', async ({ page }) => {
    const backendDetail = 'THINKING_ROLE_INTERNAL_DETAIL: incompatible judge override';
    let saves = 0;
    await page.route(url => url.pathname === '/api/config', async route => {
      if (route.request().method() !== 'PUT') {
        await route.fallback();
        return;
      }
      saves += 1;
      await route.fulfill({ status: 400, json: {
        error_code: 'INPUT_BAD_FIELD', error: backendDetail, status: 400,
      } });
    });
    await page.goto('/#/settings?tab=provider');
    const panel = page.locator('#spanel-provider');
    const budget = panel.getByRole('spinbutton', { name: 'Output token budget', exact: true });
    await budget.fill(String(Number(await budget.inputValue()) + 10000));
    await panel.locator('.settings-card__actions').getByRole('button', { name: 'Save', exact: true }).click();
    const error = panel.getByRole('alert');
    await expect(error).toContainText('Use separate provider aliases');
    await expect(panel).not.toContainText(backendDetail);
    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(error).toHaveText('请检查提供商、模型、思考等级和输出预算。需要不同设置时，请使用不同的提供商别名。');
    await expect(panel).not.toContainText(backendDetail);
    await page.getByRole('button', { name: 'English', exact: true }).click();
    await expect(error).toContainText('Use separate provider aliases');
    expect(saves).toBe(1);
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

  test('offers model-specific reasoning for Chat Completions and saves explicit off', async ({ page }) => {
    await page.route((url) => url.pathname === '/api/providers/model-limits/preview', (route) =>
      route.fulfill({ json: capabilityResponse('gpt-5.6-luna', ['none', 'low', 'medium', 'high', 'xhigh', 'max']) }));
    const payloads = await captureProviderSaves(page);
    const form = await openProviderDraft(page, 'gpt-5.6-luna');
    const thinking = form.locator('#provider-thinking-new');
    await expect(thinking).toBeEnabled();
    await expect(thinking).toHaveValue('');
    await expect(thinking.locator('option')).toHaveText([
      'Use model default', 'Off', 'Low', 'Medium', 'High', 'Extra high', 'Maximum',
    ]);
    await expect(form.locator('.provider-card__header-meta')).toContainText('openai');
    await expect(form.locator('.provider-card__header-meta')).toContainText('gpt-5.6-luna');
    await expect(form.locator('.provider-card__limits-values')).toContainText('200,000');
    await expect(form.locator('.provider-card__limits-values')).toContainText('256,000');
    await expect(form.locator('.provider-card__limits-values')).toContainText('56,000');
    await thinking.selectOption('none');
    await form.getByRole('button', { name: 'Save', exact: true }).click();
    await expect.poll(() => payloads.length).toBe(1);
    expect(payloads[0]?.thinking_level).toBe('none');
  });

  test('keeps an invalid old effort through a failed model check and recovers without silently saving it', async ({ page }) => {
    let failPreview = false;
    await page.route((url) => url.pathname === '/api/providers/model-limits/preview', async (route) => {
      const payload = route.request().postDataJSON() as { model_name: string; provider_class: string };
      if (failPreview) {
        await route.fulfill({ status: 503, json: { error: 'Capability lookup unavailable' } });
        return;
      }
      await route.fulfill({
        json: capabilityResponse(payload.model_name, payload.model_name === 'toggle-model'
          ? ['none', 'enabled'] : ['none', 'low', 'high'], payload.provider_class),
      });
    });
    const payloads = await captureProviderSaves(page);
    const form = await openProviderDraft(page, 'effort-model', 'newapi');
    const thinking = form.locator('#provider-thinking-new');
    const save = form.getByRole('button', { name: 'Save', exact: true });
    await expect(thinking).toBeEnabled();
    await thinking.selectOption('high');
    await expect(save).toBeEnabled();
    failPreview = true;
    await form.locator('#provider-model-new').fill('toggle-model');
    await expect(save).toBeDisabled();
    await expect(thinking).toHaveValue('high');
    await expect(form.getByRole('button', { name: 'Retry capability check' })).toBeVisible();
    await expect(thinking).toHaveValue('high');
    await expect(save).toBeDisabled();
    expect(payloads).toHaveLength(0);

    failPreview = false;
    await form.getByRole('button', { name: 'Retry capability check' }).click();
    await expect(thinking.locator('option[value="enabled"]')).toHaveText('On');
    await expect(thinking).toHaveValue('high');
    await expect(thinking).toHaveAttribute('aria-invalid', 'true');
    await expect(save).toBeDisabled();
    await thinking.selectOption('enabled');
    await expect(save).toBeEnabled();
    await thinking.selectOption('');
    await save.click();
    await expect.poll(() => payloads.length).toBe(1);
    expect(payloads[0]?.thinking_level).toBeNull();
    expect(payloads[0]?.model_name).toBe('toggle-model');
  });

  test('keeps the model default usable when capability lookup fails', async ({ page }) => {
    await page.route((url) => url.pathname === '/api/providers/model-limits/preview', (route) =>
      route.fulfill({ status: 503, json: { error: 'Capability lookup unavailable' } }));
    const payloads = await captureProviderSaves(page);
    const form = await openProviderDraft(page, 'private-model');
    await expect(form.getByRole('button', { name: 'Retry capability check' })).toBeVisible();
    const thinking = form.locator('#provider-thinking-new');
    await expect(thinking).toHaveValue('');
    await expect(thinking.locator('option')).toHaveText(['Use model default']);
    await form.getByRole('button', { name: 'Save', exact: true }).click();
    await expect.poll(() => payloads.length).toBe(1);
    expect(payloads[0]?.thinking_level).toBeNull();
  });

  test('allows a manual model ID after discovery and keeps unknown limits unknown', async ({ page }) => {
    await page.route((url) => url.pathname === '/api/providers/model-limits/preview', async (route) => {
      const payload = route.request().postDataJSON() as { model_name: string; provider_class: string };
      const response = capabilityResponse(payload.model_name, [], payload.provider_class);
      await route.fulfill({ json: {
        ...response,
        max_context_known: false, max_input_known: false, max_output_known: false,
        max_context_tokens: null, max_input_tokens: null, max_output_tokens: null,
        source: 'default', confidence: null,
      } });
    });
    await page.route((url) => url.pathname === '/api/providers/discover-models', (route) =>
      route.fulfill({ json: { models: ['listed-model'] } }));
    const form = await openProviderDraft(page, 'listed-model', 'openai_compat');
    await form.locator('#provider-apikey-new').fill('test-key-not-a-real-secret');
    await form.locator('.provider-card__model-discover button').click();
    await form.getByRole('button', { name: 'Enter a model ID manually' }).click();
    await form.locator('#provider-model-new').fill('private/custom-model');
    await expect(form.locator('#provider-thinking-new')).toBeEnabled();
    await expect(form.locator('#provider-model-new')).toHaveValue('private/custom-model');
    await expect(form.locator('.provider-card__header-meta')).toContainText('private/custom-model');
    await expect(form.locator('.provider-card__limits-values dd')).toHaveText(['Unknown', 'Unknown', 'Unknown']);
    await form.getByRole('button', { name: 'Choose from discovered models' }).click();
    await expect(form.locator('#provider-model-new')).toHaveValue('private/custom-model');
    await expect(form.locator('#provider-thinking-new option')).toHaveText(['Use model default']);
  });

  test('localizes default and minimal thinking without offering an unsupported off switch', async ({ page, baseURL }) => {
    if (!baseURL) throw new Error('Provider tests require a baseURL');
    await page.context().addCookies([{ name: 'ahadiff_lang', value: 'zh-CN', url: baseURL }]);
    const response = capabilityResponse('gemini-3.5-flash', ['minimal', 'low', 'medium', 'high'], 'gemini');
    response.thinking.warnings = ['thinking_minimal_not_off'];
    await page.route((url) => url.pathname === '/api/providers/model-limits/preview', (route) =>
      route.fulfill({ json: response }));
    await page.goto('/#/settings?tab=provider');
    await page.getByRole('button', { name: '添加提供商' }).click();
    const form = page.getByTestId('provider-card-new');
    await form.locator('#provider-class-new').selectOption('gemini');
    await form.locator('#provider-model-new').fill('gemini-3.5-flash');
    const thinking = form.locator('#provider-thinking-new');
    await expect(thinking).toBeEnabled();
    await expect(thinking.locator('option')).toHaveText(['使用模型默认值', '最低', '低', '中', '高']);
    await expect(form.getByText('最低等级仍会进行思考，不等同于关闭思考。')).toBeVisible();
    await thinking.selectOption('minimal');
    await expect(thinking).toHaveValue('minimal');
  });

  for (const locale of ['en', 'zh-CN'] as const) {
    test(`validates the thinking output budget before saving (${locale})`, async ({ page, baseURL }) => {
      if (!baseURL) throw new Error('Provider tests require a baseURL');
      await page.context().addCookies([{ name: 'ahadiff_lang', value: locale, url: baseURL }]);
      const response = capabilityResponse('legacy-budget-model', ['none', 'low', 'high'], 'anthropic');
      response.thinking.minimum_output_tokens = { low: 1025, high: 8193 };
      await page.route((url) => url.pathname === '/api/providers/model-limits/preview', (route) =>
        route.fulfill({ json: response }));
      const payloads = await captureProviderSaves(page);
      await page.goto('/#/settings?tab=provider');
      await page.getByRole('button', { name: locale === 'en' ? 'Add Provider' : '添加提供商' }).click();
      const form = page.getByTestId('provider-card-new');
      await form.locator('#provider-alias-input').fill('budget-provider');
      await form.locator('#provider-class-new').selectOption('anthropic');
      await form.locator('#provider-baseurl-new').fill('https://api.example.test/v1');
      await form.locator('#provider-model-new').fill('legacy-budget-model');
      const thinking = form.locator('#provider-thinking-new');
      const output = form.locator('#provider-maxout-new');
      const save = form.locator('button[type="submit"]');
      const budgetError = form.locator('#provider-thinking-budget-error-new');
      await expect(thinking).toBeEnabled();
      await thinking.selectOption('high');
      await form.locator('.provider-card__advanced summary').click();
      await output.fill('4096');
      await expect(save).toBeDisabled();
      await expect(output).toHaveAttribute('aria-invalid', 'true');
      await expect(thinking).toHaveAttribute('aria-invalid', 'true');
      await form.locator('.provider-card__advanced summary').click();
      await expect(budgetError).toBeVisible();
      await expect(budgetError).toContainText(locale === 'en'
        ? 'requires at least 8,193 output tokens'
        : '最大输出至少为 8,193 tokens');
      expect(payloads).toHaveLength(0);
      await thinking.selectOption('low');
      await expect(save).toBeEnabled();
      await thinking.selectOption('none');
      await expect(save).toBeEnabled();
      await thinking.selectOption('');
      await expect(save).toBeEnabled();
      await thinking.selectOption('high');
      await expect(save).toBeDisabled();
      await form.locator('.provider-card__advanced summary').click();
      await output.fill('');
      await expect(save).toBeEnabled();
      await output.fill('8192');
      await expect(save).toBeDisabled();
      await output.fill('8193');
      await expect(save).toBeEnabled();
      await expect(budgetError).toHaveCount(0);
      await save.click();
      await expect.poll(() => payloads.length).toBe(1);
      expect(payloads[0]?.thinking_level).toBe('high');
      expect(payloads[0]?.max_output_tokens).toBe(8193);
    });
  }
});
